#!/usr/bin/env python3
"""protograph.py: turn a short recipe into a canonical graph.yaml, check it, and
write it only after a dry run and confirmation (#399, skills/protograph/SKILL.md).

Usage:
  protograph.py RECIPE                      # dry run: print the graph + plan, write nothing
  protograph.py RECIPE --check              # exit 0 only if the emitted graph is valid
  protograph.py RECIPE --out PATH --write   # write PATH (asks first if PATH exists)
  protograph.py RECIPE --out PATH --write --yes   # confirm an overwrite without a prompt

Examples:
  protograph.py skills/protograph/examples/single-chat.recipe.yaml
  protograph.py skills/protograph/examples/from-host.recipe.yaml --check
  protograph.py my.recipe.yaml --out generated/graph-proto.yaml --write
  protograph.py --print-prompt
                        # print skills/protograph/prompts/system.md and exit

Recipe keys (see skills/protograph/SKILL.md for the full reference):
  protograph: 1                 required version marker
  host: {name, kind, os, cpu, threads, ram_mib, reserve_ram_mib}   or  host: {from_graph: NAME}
  runtime: {name, build, commit, supported_archs, backends}        or  runtime: {from_graph: NAME}
  models: {KEY: {gguf, sha256, arch, trained_ctx, role, db}  or  {from_graph: KEY}}
  nodes: [{role, model, ctx, port, [name, parallel, kv_type, flash_attn, threads, cache_ram_mib,
          status, offload, override_reasons]}]
  gateway: {port}               optional (default 8080); green-roomz gateway + one alias per node
  agent: {kind, main, [auxiliary], min_ctx}   optional (default: hermes-agent on the first node)

Every default the recipe leaves out is written explicitly into the graph
(graph.yaml has no implicit defaults). Nothing is downloaded. graph.yaml
itself is only written with --out graph.yaml --write and a confirmation; an
overwritten file is kept as PATH.bak-YYYYmmdd-HHMMSS. Output is ASCII only.
"""
from __future__ import annotations

import argparse
import copy
import errno
import os
import re
import shutil
import stat
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

# Versioned generator prompt (#327 section 2, #422 gap 7). Same files proto_chat.sh loads.
PROMPT_DIR_PARTS = ("skills", "protograph", "prompts")
PROMPT_FULL_NAME = "system.md"
PROMPT_COMPACT_NAME = "system-compact.md"
PROMPT_REL = os.path.join(*PROMPT_DIR_PARTS, PROMPT_FULL_NAME)
PROMPT_ENV = "FAMILIA_PROTOGRAPH_PROMPT"
# chars/4, matching the Race review budget. The prefix is a static file, never resized per turn.
MAX_OUTPUT_TOKENS = 512
USER_TURN_TOKENS = 256
# Reply cap for one user line: execute, feed the output back once, execute at most once more.
RUN_LIMIT = 3
RUN_TIMEOUT = 30
AUDIT_ENV = "FAMILIA_PROTO_AUDIT"
BIN_ENV = "FAMILIA_BIN"
# Short proto_chat.sh prompt from before #327. Used only when the versioned file is rejected.
FALLBACK_SYSTEM_PROMPT = (
    "You are the familia protomodel \u2014 a tiny local helper that runs on this machine.\n"
    "Help with local install and build (deps, licenses, configure, PATH).\n"
    "Help the user explore which larger models to fetch next (coding, chat, phone, vision).\n"
    "Help search the user's X/Twitter posts when Agent-Reach / twitter-cli is available.\n"
    "Keep answers short and actionable. Prefer one next command. Never claim cloud access you do not have."
)
_RUN_LINE = re.compile(r"(?m)^[ \t]*RUN:[ \t]*(.*\S)[ \t]*$")
_RUN_FENCE = re.compile(r"(?ms)^```run[ \t]*\n(.*?)\n```[ \t]*$")
_TOKEN = re.compile(r"^[A-Za-z0-9_./:=+-]+$")
_RUN_FLAGS = {"--dry-run", "--yes", "--help"}
_META = set(";&|$`<>(){}*?[]!\\'\"#\n\r\t")


class PromptLoadError(Exception):
    def __init__(self, reason, path=""):
        self.reason = reason
        self.path = path
        super().__init__(reason)


class PromptRefuse(Exception):
    """The selected ctx cannot hold a system prefix, a user turn, and the reply."""


def estimate_tokens(text):
    """Upper bound used for the ctx budget: one token per four bytes, rounded up."""
    n = len((text or "").encode("utf-8"))
    return (n + 3) // 4


def prompt_token_budget(ctx):
    """Tokens left for the system prefix after a user turn and MAX_OUTPUT_TOKENS."""
    return int(ctx) - MAX_OUTPUT_TOKENS - USER_TURN_TOKENS


def _o_nofollow():
    flag = getattr(os, "O_NOFOLLOW", 0)
    if not flag:
        raise PromptLoadError("O_NOFOLLOW unavailable")
    return flag


def _read_fd(fd, max_bytes):
    """fstat the already-open fd, then read. Never stat the path and then open it."""
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode):
        raise PromptLoadError("not a regular file")
    if max_bytes is not None and st.st_size > max_bytes:
        raise PromptLoadError("over budget")
    want = st.st_size
    data = b""
    while len(data) < want:
        chunk = os.read(fd, want - len(data))
        if not chunk:
            break
        data += chunk
        if max_bytes is not None and len(data) > max_bytes:
            raise PromptLoadError("over budget")
    return data


def _open_under_root(root, parts, max_bytes):
    """Walk parts from root with O_NOFOLLOW on every component, then fstat the fd."""
    flag = _o_nofollow()
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for i, part in enumerate(parts):
            if part in ("", ".", "..") or "/" in part or "\\" in part:
                raise PromptLoadError("outside")
            last = i == len(parts) - 1
            flags = os.O_RDONLY | flag
            if not last:
                flags |= os.O_DIRECTORY
            try:
                nxt = os.open(part, flags, dir_fd=fd)
            except OSError as exc:
                # ELOOP is a symlink (O_NOFOLLOW). ENOENT is missing. Do not follow either.
                if exc.errno == errno.ENOENT:
                    reason = "missing or empty"
                elif exc.errno in (getattr(errno, "ELOOP", -1), getattr(errno, "EPERM", -1)):
                    reason = "symlink"
                else:
                    reason = "symlink or missing"
                raise PromptLoadError(reason) from exc
            os.close(fd)
            fd = nxt
        return _read_fd(fd, max_bytes)
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def confined_prompt_name(root, override):
    """Basename inside skills/protograph/prompts, or PromptLoadError('outside')."""
    if not (override or "").strip():
        return PROMPT_FULL_NAME
    raw = override.strip()
    drive = len(raw) >= 3 and raw[0].isalpha() and raw[1] == ":" and raw[2] in "/\\"
    prompts = os.path.join(root, *PROMPT_DIR_PARTS)
    if os.path.isabs(raw) or drive:
        norm = os.path.normpath(raw)
        prefix = os.path.normpath(prompts) + os.sep
        if not norm.startswith(prefix):
            raise PromptLoadError("outside", raw)
        rest = norm[len(prefix):]
    else:
        norm = os.path.normpath(raw)
        if norm.startswith("..") or os.path.isabs(norm):
            raise PromptLoadError("outside", raw)
        rel = os.path.join(*PROMPT_DIR_PARTS)
        if norm == rel:
            raise PromptLoadError("outside", raw)
        if norm.startswith(rel + os.sep):
            rest = norm[len(rel) + 1:]
        else:
            rest = norm
    if not rest or os.sep in rest or "/" in rest or "\\" in rest or rest in (".", ".."):
        raise PromptLoadError("outside", raw)
    return rest


def read_prompt_file(root, name, max_bytes):
    """Return ASCII text of prompts/<name>. Symlinks and over-budget files raise."""
    try:
        raw = _open_under_root(root, PROMPT_DIR_PARTS + (name,), max_bytes)
    except PromptLoadError:
        raise
    except OSError as exc:
        raise PromptLoadError("missing or empty") from exc
    if not raw.strip():
        raise PromptLoadError("empty")
    try:
        return raw.decode("ascii")
    except UnicodeError as exc:
        raise PromptLoadError("not ASCII") from exc


def _is_abs_prompt(path):
    """True for a POSIX absolute path or a Windows drive path (even on POSIX)."""
    if os.path.isabs(path):
        return True
    return len(path) >= 3 and path[0].isalpha() and path[1] == ":" and path[2] in "/\\"


def system_prompt_path(root=None, override=None):
    """Path the loader will consider. A relative override is under root, not the cwd."""
    root = root or ROOT
    if override is None:
        override = os.environ.get(PROMPT_ENV, "")
    override = (override or "").strip()
    if not override:
        return os.path.join(root, *PROMPT_DIR_PARTS, PROMPT_FULL_NAME)
    if _is_abs_prompt(override):
        return override
    return os.path.join(root, override)


def graph_ctx_values(graph=None):
    """Sorted unique nodes.*.ctx values from graph.yaml."""
    if graph is None:
        import familia_yaml
        path = os.environ.get("FAMILIA_GRAPH") or os.path.join(ROOT, "graph.yaml")
        graph = familia_yaml.load(path) or {}
    found = set()
    for node in (graph.get("nodes") or {}).values():
        if isinstance(node, dict) and isinstance(node.get("ctx"), int):
            found.add(node["ctx"])
    return sorted(found)


def ctx_for_model(model_id, graph=None):
    """Ctx of the graph node or alias named by model_id, else None when the id is unknown."""
    if graph is None:
        import familia_yaml
        path = os.environ.get("FAMILIA_GRAPH") or os.path.join(ROOT, "graph.yaml")
        graph = familia_yaml.load(path) or {}
    name = (model_id or "").strip()
    nodes = graph.get("nodes") or {}
    if name in nodes and isinstance(nodes[name], dict) and isinstance(nodes[name].get("ctx"), int):
        return nodes[name]["ctx"]
    aliases = graph.get("aliases") or {}
    alias = aliases.get(name)
    if isinstance(alias, dict):
        node = alias.get("node")
        if node in nodes and isinstance(nodes[node].get("ctx"), int):
            return nodes[node]["ctx"]
    # Longest node name contained in the id (server ids sometimes carry a suffix).
    best = ""
    for node, spec in nodes.items():
        if isinstance(spec, dict) and isinstance(spec.get("ctx"), int) and node in name and len(node) > len(best):
            best = node
    if best:
        return nodes[best]["ctx"]
    return None


def _greeting_text(greeting):
    if greeting is not None:
        return greeting
    import fleet_greeting
    return fleet_greeting.load() or ""


def _assembled(body, greeting):
    if not greeting:
        return body
    import fleet_greeting
    return fleet_greeting.prepend(body, greeting=greeting)


def _fits(body, greeting, ctx):
    return estimate_tokens(_assembled(body, greeting)) + USER_TURN_TOKENS + MAX_OUTPUT_TOKENS <= int(ctx)


def select_system_prompt(ctx, root=None, override=None, greeting=None):
    """Return (text, variant, used_fallback, warning).

    variant is 'full', 'compact', or 'fallback'. The text is a static file
    (or the built-in fallback): nothing in it depends on ctx, so the prefix
    is reusable. Over budget selects the compact file. A symlink, a path
    outside skills/protograph/prompts, or a non-ASCII file falls back.
    """
    root = root or ROOT
    if override is None:
        override = os.environ.get(PROMPT_ENV, "")
    greeting = _greeting_text(greeting)
    budget = prompt_token_budget(ctx)
    if budget <= 0:
        raise PromptRefuse(
            f"ctx {ctx} cannot hold a {USER_TURN_TOKENS}-token user turn and "
            f"{MAX_OUTPUT_TOKENS} output tokens"
        )
    # Byte cap is the ctx budget minus the greeting, not a fixed raw size.
    gtok = estimate_tokens(_assembled("", greeting)) if greeting else 0
    # _assembled("", greeting) still prepends a newline before an empty body.
    # Budget the greeting block the same way prepend does for a real body.
    if greeting:
        import fleet_greeting
        gtok = estimate_tokens(fleet_greeting.block(greeting) + "\n")
    file_tokens = budget - gtok
    if file_tokens <= 0:
        raise PromptRefuse(
            f"ctx {ctx} has no room for a system prompt after the fleet greeting, "
            f"a user turn, and {MAX_OUTPUT_TOKENS} output tokens"
        )
    max_bytes = file_tokens * 4
    warning = ""
    try:
        name = confined_prompt_name(root, override)
    except PromptLoadError as exc:
        warning = f"protograph prompt file outside the prompts directory ({exc.path or override}); using the short fallback"
        if _fits(FALLBACK_SYSTEM_PROMPT, greeting, ctx):
            return FALLBACK_SYSTEM_PROMPT, "fallback", True, warning
        raise PromptRefuse(warning) from exc
    try:
        text = read_prompt_file(root, name, max_bytes)
        if _fits(text, greeting, ctx):
            variant = "compact" if name == PROMPT_COMPACT_NAME else "full"
            return text, variant, False, ""
        raise PromptLoadError("over budget")
    except PromptLoadError as exc:
        if exc.reason == "over budget" and name == PROMPT_FULL_NAME:
            try:
                compact = read_prompt_file(root, PROMPT_COMPACT_NAME, max_bytes)
                if "RUN: ./familia" not in compact:
                    raise PromptLoadError("compact missing run directive")
                if _fits(compact, greeting, ctx):
                    return compact, "compact", False, ""
            except PromptLoadError:
                pass
            raise PromptRefuse(
                f"ctx {ctx}: the full and compact system prompts do not leave room for "
                f"a user turn and {MAX_OUTPUT_TOKENS} output tokens"
            ) from exc
        warning = f"protograph prompt file {exc.reason} ({name}); using the short fallback"
        if _fits(FALLBACK_SYSTEM_PROMPT, greeting, ctx):
            return FALLBACK_SYSTEM_PROMPT, "fallback", True, warning
        raise PromptRefuse(warning) from exc


def load_system_prompt(root=None, override=None, ctx=8192, greeting=""):
    """Return (text, path, used_fallback). PromptRefuse if even the fallback does not fit."""
    root = root or ROOT
    path = system_prompt_path(root, override)
    text, _variant, fallback, warning = select_system_prompt(
        ctx, root=root, override=override, greeting=greeting)
    if warning:
        print(f"protograph: warning: {warning}", file=sys.stderr)
    return text, path, fallback

def parse_run_directives(text):
    """RUN: lines and ```run fences, in order, capped at RUN_LIMIT."""
    found = []
    for match in _RUN_LINE.finditer(text or ""):
        found.append(match.group(1).strip())
    for match in _RUN_FENCE.finditer(text or ""):
        for line in match.group(1).splitlines():
            line = line.strip()
            if line.startswith("RUN:"):
                line = line[4:].strip()
            if line:
                found.append(line)
    return found[:RUN_LIMIT]


def vet_familia_command(line):
    """Return (argv, None) or (None, reason). argv[0] is the literal ./familia, not a path to exec."""
    if any(ch in _META or ord(ch) < 32 or ord(ch) > 126 for ch in line):
        return None, "metacharacter"
    parts = line.split()
    if len(parts) > 32:
        return None, "too many arguments"
    if not parts or parts[0] not in ("./familia", "familia"):
        return None, "not a familia command"
    args = parts[1:]
    if any(_TOKEN.fullmatch(arg) is None for arg in args):
        return None, "metacharacter"
    flags, i = [], 0
    while i < len(args) and args[i] in _RUN_FLAGS:
        flags.append(args[i])
        i += 1
    rest = args[i:]
    if not rest:
        return None, "missing subcommand"
    import familia_cli
    hit, _k = familia_cli.resolve(rest)
    if not hit or hit[0] != "item":
        return None, "not in scripts/menu-items.txt"
    return ["./familia", *flags, *rest], None


def _audit(command, code, path=None):
    path = os.environ.get(AUDIT_ENV) if path is None else path
    if path is None:
        path = os.path.join(ROOT, ".cache", "proto-run.log")
    if path == "":
        return
    safe = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in str(command))[:240]
    line = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) + "\t" + safe + "\t" + str(code) + "\n"
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | _o_nofollow()
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        print(f"protograph: warning: audit log not written ({exc.errno})", file=sys.stderr)
        return
    try:
        os.write(fd, line.encode("ascii"))
    finally:
        os.close(fd)


def execute_familia(line, bin_path=None, timeout=None, audit=None):
    """Exec one vetted familia command. shell=False. The model never chooses argv[0]."""
    argv, err = vet_familia_command(line)
    if err:
        _audit(line, "refused", audit)
        return {"status": "refused", "exit": "refused", "reason": err, "output": "", "argv": []}
    exe = bin_path if bin_path is not None else (os.environ.get(BIN_ENV) or os.path.join(ROOT, "familia"))
    if not os.path.isabs(exe):
        exe = os.path.join(ROOT, exe)
    if timeout is None:
        timeout = float(os.environ.get("FAMILIA_PROTO_RUN_TIMEOUT", RUN_TIMEOUT))
    cmd = [exe, *argv[1:]]
    try:
        proc = subprocess.run(cmd, shell=False, capture_output=True, timeout=timeout, cwd=ROOT)
    except subprocess.TimeoutExpired as exc:
        _audit(" ".join(argv), "timeout", audit)
        out = (exc.stdout or b"") + (exc.stderr or b"")
        return {"status": "timeout", "exit": "timeout", "reason": "timeout",
                "output": out.decode("utf-8", "replace"), "argv": argv}
    _audit(" ".join(argv), proc.returncode, audit)
    out = proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")
    return {"status": "ran", "exit": proc.returncode, "reason": "", "output": out, "argv": argv}


def format_exec_result(result):
    lines = [f"status: {result['status']}", f"exit: {result['exit']}"]
    if result.get("reason"):
        lines.append(f"reason: {result['reason']}")
    if result.get("argv"):
        lines.append("argv: " + " ".join(result["argv"]))
    lines.append("---")
    lines.append(result.get("output") or "")
    return "\n".join(lines).rstrip("\n") + "\n"


def execute_reply(text, **kwargs):
    """Run every directive in a model reply. Empty string when there is nothing to run."""
    chunks = [format_exec_result(execute_familia(line, **kwargs)) for line in parse_run_directives(text)]
    return "".join(chunks)


import yaml  # noqa: E402

NODE_DEFAULTS = {"parallel": 1, "kv_type": "f16", "flash_attn": False, "bind": "127.0.0.1",
                 "cache_ram_mib": 0, "status": "active"}
HOST_KEYS = ("kind", "os", "cpu", "threads", "ram_mib", "reserve_ram_mib")
MIB = 1048576.0


class RecipeError(Exception):
    pass


def _base_graph(recipe_dir, ref_graph=None):
    path = ref_graph or os.environ.get("FAMILIA_GRAPH") or os.path.join(ROOT, "graph.yaml")
    if not os.path.isabs(path) and not os.path.exists(path):
        path = os.path.join(recipe_dir, path)
    import familia_yaml
    return familia_yaml.load(path) or {}


def build(recipe, recipe_dir=".", ref_graph=None):
    """recipe dict -> (graph dict, plan lines). Raises RecipeError on an incomplete or unsafe recipe."""
    if not isinstance(recipe, dict) or recipe.get("protograph") != 1:
        raise RecipeError("recipe must start with 'protograph: 1'")
    unknown = set(recipe) - {"protograph", "host", "runtime", "models", "nodes", "gateway", "agent", "graph", "notes"}
    if unknown:
        raise RecipeError(f"unknown recipe key(s): {', '.join(sorted(unknown))}")
    plan, base = [], None

    def ref():
        nonlocal base
        if base is None:
            base = _base_graph(recipe_dir, recipe.get("graph") or ref_graph)
        return base

    h = recipe.get("host") or {}
    if "from_graph" in h:
        name = h["from_graph"]
        src = (ref().get("hosts") or {}).get(name)
        if not src:
            raise RecipeError(f"host.from_graph: no host {name!r} in the reference graph")
        host = {k: v for k, v in copy.deepcopy(src).items()}
        host["addr"], host["user"] = "REPLACE_ME", "REPLACE_ME"   # privacy (#104): never copy real addr/user
        plan.append(f"host {name}: copied from the reference graph (addr/user left as REPLACE_ME)")
    else:
        name = h.get("name")
        missing = [k for k in ("name",) + HOST_KEYS if h.get(k) is None]
        if missing:
            raise RecipeError(f"host: missing {', '.join(missing)} (or use host: {{from_graph: NAME}})")
        host = {"kind": h["kind"], "measured": bool(h.get("measured", False)), "os": h["os"], "cpu": h["cpu"],
                "threads": h["threads"], "ram_mib": h["ram_mib"], "reserve_ram_mib": h["reserve_ram_mib"],
                "gpus": h.get("gpus", [])}
        plan.append(f"host {name}: from the recipe (measured: {host['measured']})")
    r = recipe.get("runtime") or {}
    if "from_graph" in r:
        rname = r["from_graph"]
        rt = copy.deepcopy((ref().get("runtimes") or {}).get(rname))
        if not rt:
            raise RecipeError(f"runtime.from_graph: no runtime {rname!r} in the reference graph")
        rt["hosts"] = [name]
        plan.append(f"runtime {rname}: copied from the reference graph")
    else:
        missing = [k for k in ("name", "build", "commit", "supported_archs", "backends") if r.get(k) in (None, [])]
        if missing:
            raise RecipeError(f"runtime: missing {', '.join(missing)} (or use runtime: {{from_graph: NAME}})")
        rname = r["name"]
        rt = {"kind": r.get("kind", "llama-server"), "build": r["build"], "commit": r["commit"], "hosts": [name],
              "supported_archs": list(r["supported_archs"]), "backends": list(r["backends"]),
              "spec_types": list(r.get("spec_types", []))}
        # bin and url are not accepted from recipe-authored runtimes (must come from from_graph or pins)
        if "sha256" in r:
            rt["sha256"] = r["sha256"]
    models = {}
    for key, m in (recipe.get("models") or {}).items():
        if isinstance(m, dict) and "from_graph" in m:
            src = (ref().get("models") or {}).get(m["from_graph"])
            if not src:
                raise RecipeError(f"models.{key}.from_graph: no model {m['from_graph']!r} in the reference graph")
            models[key] = copy.deepcopy(src)
            plan.append(f"model {key}: copied from reference models.{m['from_graph']}")
        else:
            missing = [k for k in ("gguf", "sha256", "arch", "trained_ctx", "role", "db") if not (m or {}).get(k)]
            if missing:
                raise RecipeError(f"models.{key}: missing {', '.join(missing)}")
            models[key] = dict(m)
    if not models:
        raise RecipeError("models: at least one model is required")
    nodes_in = recipe.get("nodes") or []
    if not nodes_in:
        raise RecipeError("nodes: at least one node is required")
    nodes, ports = {}, set()
    for i, n in enumerate(nodes_in):
        missing = [k for k in ("role", "model", "ctx", "port") if n.get(k) is None]
        if missing:
            raise RecipeError(f"nodes[{i}]: missing {', '.join(missing)}")
        key = n.get("name") or n["role"]
        if key in nodes:
            raise RecipeError(f"nodes[{i}]: duplicate node {key!r} (one node per role per host; give 'name')")
        if n["model"] not in models:
            raise RecipeError(f"nodes[{i}]: model {n['model']!r} is not in models:")
        if n["port"] in ports:
            raise RecipeError(f"nodes[{i}]: port {n['port']} used twice")
        ports.add(n["port"])
        bind = n.get("bind", NODE_DEFAULTS["bind"])
        if bind not in ("127.0.0.1", "::1", "localhost"):
            raise RecipeError(f"nodes[{i}]: bind {bind!r} is not loopback; protograph only emits loopback nodes "
                              f"(edit graph.yaml by hand for LAN exposure)")
        node = {"model": n["model"], "host": name, "runtime": rname, "ctx": n["ctx"]}
        model_role = (models[n["model"]].get("role") or "").strip().lower()
        node_role = (n.get("role") or "").strip().lower()
        fail_closed = ("guardian", "pentest", "defender")
        if node_role != model_role:
            if node_role in fail_closed or model_role in fail_closed:
                raise RecipeError(
                    f"nodes[{i}]: role override {node_role!r} over {model_role!r} model refused; "
                    f"fail-closed models cannot be overridden to routable roles"
                )
            node["role"] = n["role"]
        for k, d in NODE_DEFAULTS.items():
            node[k] = n.get(k, d)
            if k not in n:
                plan.append(f"node {key}: {k} = {d!r} (recipe default)")
        if "threads" in n:
            node["threads"] = n["threads"]
        if n.get("override_reasons"):
            node["override_reasons"] = dict(n["override_reasons"])   # model-card deviations (#51)
        node["offload"] = n.get("offload", {"backend": "cpu", "ngl": 0, "split": "none", "main_gpu": 0})
        node["port"] = n["port"]
        nodes[key] = node
    g = {"version": 2, "hosts": {name: host}, "runtimes": {rname: rt}, "models": models, "nodes": nodes}
    gw = recipe.get("gateway")
    if not gw:
        gw = {"port": 8080}
        plan.append("gateway: green-roomz on port 8080 (recipe default; the graph needs one)")
    if gw.get("port") in ports:
        raise RecipeError(f"gateway port {gw['port']} conflicts with node port")
    if True:
        g["gateways"] = {"gw": {"kind": "green-roomz", "host": name, "port": gw["port"]}}
        g["aliases"] = {k: {"node": k, "gateway": "gw"} for k in nodes}
    ag = recipe.get("agent")
    if not ag:
        ag = {"main": next(iter(nodes))}
        plan.append(f"agent ag: hermes-agent on alias {ag['main']} (recipe default; the graph needs one)")
    if True:
        main = ag.get("main")
        if main not in nodes:
            raise RecipeError(f"agent.main: {main!r} is not a node")
        aux = ag.get("auxiliary", main)
        ctx = nodes[main]["ctx"] // nodes[main]["parallel"]
        g["agents"] = {ag.get("name", "ag"): {"kind": ag.get("kind", "hermes-agent"), "host": name,
                                              "min_ctx": ag.get("min_ctx", ctx), "context_length": ctx,
                                              "aliases": {"main": main, "auxiliary": aux}}}
    return g, plan


def ram_report(g):
    """Rough RAM check: model file (or model-db bytes) + cache_ram per active node vs host budget."""
    lines, bad = [], False
    for hn, h in g["hosts"].items():
        budget = (h.get("ram_mib") or 0) - (h.get("reserve_ram_mib") or 0)
        tot, unknown = 0.0, []
        for nn, n in g["nodes"].items():
            if n["host"] != hn or n.get("status") == "planned":
                continue
            m = g["models"][n["model"]]
            p = os.path.expanduser(str(m.get("gguf", "")))
            size = os.path.getsize(p) if os.path.isfile(p) else None
            if size is None:
                try:
                    import model_db
                    size = (model_db.load(m.get("db")) or {}).get("bytes")
                except Exception:
                    size = None
            if size is None:
                unknown.append(nn)
                continue
            tot += size / MIB + (n.get("cache_ram_mib") or 0)
        ok = tot <= budget
        bad |= not ok
        lines.append(f"RAM {hn}: est. {tot:.0f} MiB of {budget} MiB budget (ram_mib - reserve_ram_mib)"
                     f"{' OK' if ok else ' OVER BUDGET'}" + (f"; size unknown: {', '.join(unknown)}" if unknown else ""))
    return lines, bad


def check(g):
    import validate_graph
    errs, _ = validate_graph.validate(copy.deepcopy(g), check_files=False)
    ram, over = ram_report(g)
    if over:
        errs = list(errs) + [l for l in ram if "OVER" in l]
    return errs, ram, list(validate_graph.WARNINGS)


def dump(g, recipe_path):
    head = (f"# Generated by scripts/protograph.py from {recipe_path} (#399).\n"
            "# Every value is explicit; edit the recipe and regenerate rather than hand-editing.\n")
    return head + yaml.safe_dump(g, sort_keys=False, allow_unicode=False, default_flow_style=False)


def confirm(path, yes):
    if yes:
        return True
    if not (sys.stdin.isatty() and os.environ.get("FAMILIA_NO_TTY") != "1"):
        return False
    return input(f"{path} exists. Overwrite (a backup is kept)? [y/N] ").strip().lower() in ("y", "yes")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="protograph.py", description=__doc__.split("\n")[0],
                                 epilog="Example: protograph.py skills/protograph/examples/single-chat.recipe.yaml",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("recipe", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--yes", action="store_true", help="confirm an overwrite without asking")
    ap.add_argument("--check", action="store_true", help="validate only; print errors, exit 1 if any")
    ap.add_argument("--graph", help="reference graph for from_graph (default FAMILIA_GRAPH or graph.yaml)")
    ap.add_argument("--force", action="store_true", help="write even when validation fails (never for graph.yaml)")
    ap.add_argument("--print-prompt", action="store_true",
                    help="print the versioned protograph system prompt and exit")
    ap.add_argument("--ctx", type=int, help="node ctx used to pick the full or compact prompt")
    ap.add_argument("--model", default="", help="graph node or alias whose ctx picks the prompt")
    ap.add_argument("--exec-reply", metavar="FILE", help="execute RUN directives in FILE and print the results")
    a = ap.parse_args(argv)
    if a.exec_reply:
        with open(a.exec_reply, encoding="utf-8", errors="replace") as fh:
            sys.stdout.write(execute_reply(fh.read()))
        return 0
    if a.print_prompt:
        ctx = a.ctx
        if ctx is None and a.model:
            ctx = ctx_for_model(a.model)
        if ctx is None:
            ctx = 8192
        try:
            text, _variant, _fallback, warning = select_system_prompt(ctx)
        except PromptRefuse as exc:
            print(f"protograph: error: {exc}", file=sys.stderr)
            return 3
        if warning:
            print(f"protograph: warning: {warning}", file=sys.stderr)
        sys.stdout.write(text if text.endswith("\n") else text + "\n")
        return 0
    if not a.recipe:
        ap.error("the following arguments are required: recipe")
    try:
        with open(a.recipe, encoding="utf-8") as f:
            recipe = yaml.safe_load(f)
        g, plan = build(recipe, os.path.dirname(os.path.abspath(a.recipe)), a.graph)
    except (OSError, yaml.YAMLError, RecipeError) as e:
        print(f"protograph: ERROR: {e}", file=sys.stderr)
        return 1
    errs, ram, warns = check(g)
    for w in warns:
        print(f"protograph: WARNING: {w}", file=sys.stderr)
    for e in errs:
        print(f"protograph: ERROR: {e}", file=sys.stderr)
    if a.check:
        print("protograph: OK" if not errs else f"protograph: {len(errs)} error(s)")
        return 1 if errs else 0
    text = dump(g, a.recipe)
    if not a.write:
        print("# plan:")
        for l in plan + ram:
            print(f"#   {l}")
        print(f"# validate_graph (no file checks): {'OK' if not errs else 'ERRORS (see stderr)'}")
        print(f"# dry run: nothing written{' (would write ' + a.out + ')' if a.out else ''}; add --out PATH --write")
        print(text, end="")
        return 1 if errs else 0
    if not a.out:
        print("protograph: ERROR: --write needs --out PATH", file=sys.stderr)
        return 2
    is_main = os.path.abspath(a.out) == os.path.abspath(os.path.join(ROOT, "graph.yaml"))
    if errs and (not a.force or is_main):
        print("protograph: not written: validation failed" + (" (graph.yaml is never force-written)" if is_main else
              " (--force writes anyway)"), file=sys.stderr)
        return 1
    if os.path.exists(a.out):
        if not confirm(a.out, a.yes):
            print(f"protograph: not written: {a.out} exists; rerun with --yes to confirm the overwrite", file=sys.stderr)
            return 1
        bak = a.out + time.strftime(".bak-%Y%m%d-%H%M%S")
        shutil.copy2(a.out, bak)
        print(f"protograph: kept the old file as {bak}")
    d = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(d, exist_ok=True)
    tmp = a.out + ".tmp"
    with open(tmp, "w", encoding="ascii", errors="strict") as f:
        f.write(text)
    os.replace(tmp, a.out)
    print(f"protograph: wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
