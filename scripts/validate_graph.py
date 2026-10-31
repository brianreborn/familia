#!/usr/bin/env python3
"""Validate familia graph.yaml against GGUF metadata, hardware and agent needs.

usage: validate_graph.py [GRAPH.yaml] [--graph FILE] [--host HOST] [--no-files] [--verify-sha]
                         [--check-runtimes] [--check-swap] [--args NODE | --explain NODE] [-h|--help]

Example: validate_graph.py graph.yaml --no-files

Exit 0 when valid, 1 with one line per problem otherwise (2 for a usage error).
--args NODE      print the llama-server arguments for that node: graph settings plus every
                 REQUIRED and RECOMMENDED model parameter from the model database (#51,
                 docs/model-params.md); exits 1 when a REQUIRED one cannot be met.
--explain NODE   the same, one parameter per line with its class and source, plus the
                 client-side requirements (prompt prefixes, endpoints, stop strings).
--host HOST      scope local artifact, runtime, and RAM checks to this declared graph host.
--no-files       skip GGUF/RAM checks (schema only); --verify-sha hashes GGUFs.
--check-runtimes check that runtime binaries are executable.
--check-swap     for active nodes with swap_budget_mib (scoped by --host when set), fail if
                 host swap total MiB is below the budget (SSD/VVRAM ops gate; docs/vvram-ssd/LAYER.md).
Never guesses or inflates. Schema: scripts/graph_types.py, docs/graph-types.md.
"""
import hashlib, json, os, struct, sys
import yaml
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from graph_types import validate_types, TYPES  # noqa: E402

KV_BYTES = {"f16": 2.0, "bf16": 2.0, "q8_0": 1.0625, "q4_0": 0.5625, "f32": 4.0}

def gguf_meta(path):
    """Minimal GGUF v2/v3 metadata reader (stdlib only)."""
    out = {}
    with open(path, "rb") as f:
        if f.read(4) != b"GGUF":
            raise ValueError("not a GGUF file")
        ver, = struct.unpack("<I", f.read(4))
        if ver < 2:
            raise ValueError(f"unsupported GGUF version {ver}")
        _, n_kv = struct.unpack("<QQ", f.read(16))
        fmt = {0:"<B",1:"<b",2:"<H",3:"<h",4:"<I",5:"<i",6:"<f",7:"<?",10:"<Q",11:"<q",12:"<d"}
        def rstr():
            n, = struct.unpack("<Q", f.read(8)); return f.read(n).decode("utf-8", "replace")
        def rval(t):
            if t == 8: return rstr()
            if t == 9:
                et, n = struct.unpack("<IQ", f.read(12))
                if et in fmt and et != 8:
                    f.seek(struct.calcsize(fmt[et]) * n, 1); return ("array", n, None)
                h = hashlib.sha256() if et == 8 else None
                for _ in range(n):
                    v = rval(et)
                    if h is not None: h.update(v.encode() + b"\0")
                return ("array", n, h.hexdigest() if h else None)
            s = fmt[t]; return struct.unpack(s, f.read(struct.calcsize(s)))[0]
        for _ in range(n_kv):
            k = rstr(); t, = struct.unpack("<I", f.read(4)); out[k] = rval(t)
    return out

def vocab(meta):
    """(tokenizer model, n_vocab, sha256 of the token list) from GGUF metadata."""
    t = meta.get("tokenizer.ggml.tokens")
    n, h = (t[1], t[2]) if isinstance(t, tuple) else (None, None)
    return meta.get("tokenizer.ggml.model"), n, h

def kv_mib(meta, arch, ctx, kv_type):
    g = lambda k: meta.get(f"{arch}.{k}")
    layers, heads_kv, emb, heads = g("block_count"), g("attention.head_count_kv"), g("embedding_length"), g("attention.head_count")
    if not all(isinstance(x, int) and x for x in (layers, heads_kv, emb, heads)):
        return None
    head_dim = g("attention.key_length") or emb // heads
    # Hybrid models (e.g. qwen35) keep KV only on every Nth full-attention
    # layer; the rest carry a small fixed recurrent state.
    interval = g("full_attention_interval")
    attn_layers = -(-layers // interval) if isinstance(interval, int) and interval > 1 else layers
    kv = 2 * attn_layers * heads_kv * head_dim * ctx * KV_BYTES[kv_type]
    ssm_inner, ssm_state = g("ssm.inner_size"), g("ssm.state_size")
    if isinstance(ssm_inner, int) and isinstance(ssm_state, int):
        kv += (layers - attn_layers) * ssm_inner * ssm_state * 4  # f32 recurrent state
    return kv / 2**20

class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate keys: a second alias/node with the same name must not silently win."""
    def construct_mapping(self, node, deep=False):
        seen = set()
        for k, _ in node.value:
            key = self.construct_object(k, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", k.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep)

def load(path):
    with open(path) as f:
        return yaml.load(f, Loader=UniqueKeyLoader)

WARNINGS = []  # margin-only RAM guidance from the last validate() call

def validate(graph, check_files=True, host=None):
    del WARNINGS[:]
    """Typed schema check, then GGUF/RAM checks. Returns (errors, {host: est MiB})."""
    errs = validate_types(graph)
    if not errs:  # model database (#51): every node's model has a pinned, card-checked entry
        import model_db
        de, dw = model_db.check_graph(graph)
        errs += de
        WARNINGS.extend(dw)
    if not errs:  # every launched node gets its REQUIRED model parameters (#51)
        for nn, nd in graph["nodes"].items():
            if nd.get("status") == "planned": continue
            if (graph["runtimes"].get(nd["runtime"]) or {}).get("kind", "llama-server") != "llama-server": continue
            try: server_args(graph, nn)
            except SystemExit as ex: errs += [l.replace("graph: ERROR: ", "") for l in str(ex).split("\n") if l]
    errs = list(dict.fromkeys(errs))
    if errs or not check_files:
        return errs, {}
    # Host scope (same rule as check_swap_budgets): file-existence and RAM totals are only
    # meaningful on the machine that runs them. --host naming another graph host skips them;
    # with no --host, scope to this machine's graph host when it resolves.
    try:
        from start_graph import select_host
        local = select_host(graph)
    except BaseException:
        local = None
    if local not in (graph.get("hosts") or {}):
        local = None
    if host is not None and local is not None and host != local:
        WARNINGS.append(f"file/RAM checks skipped: this machine is graph host {local!r}, not {host!r}; "
                        f"run validate_graph --host {host} on {host}")
        return errs, {}
    if host is None:
        host = local
    hosts, models, totals = graph["hosts"], graph["models"], {}
    base = os.path.dirname(os.path.abspath(graph.get("_path", "graph.yaml")))
    for rn, r in graph["runtimes"].items():
        if "bin" in r and "--check-runtimes" in sys.argv and (host is None or host in r.get("hosts", [])):
            b = os.path.join(base, os.path.expanduser(r["bin"]))
            if not os.access(b, os.X_OK): errs.append(f"runtimes.{rn}: binary not executable: {b}"); continue
            import subprocess
            v = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=30)
            if str(r["commit"])[:9] not in v.stdout + v.stderr: errs.append(f"runtimes.{rn}: {b} does not report commit {r['commit']}")
    metas = {}
    for name, n in graph["nodes"].items():
        if n["status"] == "planned": continue
        if host is not None and n["host"] != host: continue
        m = models[n["model"]]
        rt = graph["runtimes"].get(n["runtime"]) or {}
        # sm11-legacy / llama2.c .bin checkpoints are not GGUF
        if rt.get("kind") == "sm11-legacy" or str(m.get("gguf", "")).endswith(".bin"):
            path = os.path.expanduser(m["gguf"])
            if os.path.isfile(path):
                totals[n["host"]] = totals.get(n["host"], 0.0) + os.path.getsize(path) / 2**20 + n.get("cache_ram_mib", 0)
            continue
        path = os.path.expanduser(m["gguf"])
        if not os.path.isfile(path):
            errs.append(f"nodes.{name}: model file not found: {path}"); continue
        try: meta = gguf_meta(path)
        except Exception as e: errs.append(f"nodes.{name}: cannot read GGUF: {e}"); continue
        arch = meta.get("general.architecture")
        _ARCH_ALIAS = {"llama": "nanbeige", "nanbeige": "llama"}
        if arch != m["arch"] and _ARCH_ALIAS.get(arch) != m["arch"] and _ARCH_ALIAS.get(m["arch"]) != arch:
            errs.append(f"models.{n['model']}: GGUF architecture is {arch!r}, graph says {m['arch']!r}")
        fq, mq = meta.get("familia.quant"), m.get("quant")  # LittleBit (docs/littlebit.md)
        if fq == "littlebit" and mq != "littlebit": errs.append(f"models.{n['model']}: model is a LittleBit file (familia.quant=littlebit); model must declare quant: littlebit")
        if mq == "littlebit" and fq != "littlebit": errs.append(f"models.{n['model']}: quant: littlebit but {path} has no familia.quant=littlebit marker")
        if mq == "littlebit" and fq == "littlebit" and meta.get("littlebit.format_version") != 1:
            errs.append(f"models.{n['model']}: unsupported littlebit.format_version {meta.get('littlebit.format_version')!r} (this validator knows 1)")
        df = m.get("derived_from")
        if df:  # produced by scripts/scale_down.py (docs/scale-down.md)
            w = f"models.{n['model']}.derived_from"
            mp = os.path.join(os.path.dirname(os.path.abspath(graph.get("_path", "graph.yaml"))), os.path.expanduser(df.get("manifest", "")))
            try: rec = json.load(open(mp))
            except Exception as e: errs.append(f"{w}: manifest unreadable: {e}"); rec = {}
            if rec and rec.get("output_sha256") != df.get("sha256"): errs.append(f"{w}: sha256 does not match manifest")
            if rec and rec.get("output_bytes") != os.path.getsize(path): errs.append(f"{w}: model size differs from scale-down manifest (file changed?)")
            if rec and rec.get("source_bytes") and os.path.getsize(path) >= rec["source_bytes"]: errs.append(f"{w}: scaled model is not smaller than its source")
            if rec and rec.get("arch") != arch: errs.append(f"{w}: scaled arch {arch!r} != manifest arch {rec.get('arch')!r}")
            src = models.get(df.get("model"))
            if src is not None and src.get("arch") != arch: errs.append(f"{w}: arch {arch!r} differs from source model {df.get('model')} ({src.get('arch')!r})")
        train = meta.get(f"{arch}.context_length")
        if isinstance(train, int) and train != m["trained_ctx"]:
            errs.append(f"models.{n['model']}: trained_ctx {m['trained_ctx']} but GGUF says {train}")
        if m["sha256"] != "unmeasured" and "--verify-sha" in sys.argv:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
            if h.hexdigest() != m["sha256"]: errs.append(f"models.{n['model']}: sha256 mismatch ({h.hexdigest()})")
        metas[name] = meta
        kv = kv_mib(meta, arch, n["ctx"], n["kv_type"])
        layers = meta.get(f"{arch}.block_count")
        ngl = n["offload"]["ngl"]
        if ngl and isinstance(layers, int):
            gpus = hosts[n["host"]].get("gpus")
            gpu_index = n["offload"]["main_gpu"]
            if not isinstance(gpus, list) or gpu_index >= len(gpus):
                continue
            gp = gpus[gpu_index]
            frac = min(ngl, layers + 1) / (layers + 1)
            need = frac * (os.path.getsize(path) / 2**20 + (kv or 0)) + n["offload"].get("vram_reserve_mib", 0)
            if isinstance(gp.get("vram_mib"), int) and need > gp["vram_mib"]:
                errs.append(f"nodes.{name}: offload ngl {ngl} needs ~{need:.0f} MiB VRAM > GPU {n['offload']['main_gpu']} vram_mib {gp['vram_mib']}")
        # Prompt-cache state for one full slot is roughly that slot's KV; if
        # --cache-ram is smaller, llama.cpp skips caching on every request.
        state = kv_mib(meta, arch, n["ctx"] // n["parallel"], n["kv_type"])
        if n.get("embeddings"): state = None  # embedding servers keep no prompt cache
        if state is not None and n["cache_ram_mib"] < state:
            msg = (
                f"nodes.{name}: cache_ram_mib {n['cache_ram_mib']} < estimated per-slot prompt state "
                f"{state:.0f} MiB (prompt cache would always be skipped)"
            )
            # Phones stay strict (no big swap). Swap-rich desktops/laptops/servers: advisory only.
            hk = (hosts.get(n["host"]) or {}).get("kind")
            hos = str((hosts.get(n["host"]) or {}).get("os") or "").lower()
            androidish = hk == "phone" or hos.startswith("android")
            if androidish:
                errs.append(msg)
            else:
                WARNINGS.append(msg + " (non-Android: advisory; raise cache_ram_mib when you want prompt cache)")
        weight_mib = os.path.getsize(path) / 2**20
        # Software VVRAM (docs/vvram-ssd/LAYER.md): mmap + swap_budget means weights are
        # file/swap-backed; counting the full GGUF as RAM hard-fails Nanbeige on 24 GiB hosts.
        # Still charge KV + cache_ram + overhead; warn so operators keep swap measured.
        if n.get("load_mode") == "mmap" and n.get("swap_budget_mib"):
            WARNINGS.append(
                f"nodes.{name}: mmap+swap_budget — GGUF {weight_mib:.0f} MiB not charged to hard RAM total"
            )
            weight_mib = 0.0
        totals[n["host"]] = totals.get(n["host"], 0.0) + weight_mib + (kv or 0) + 256 + n["cache_ram_mib"]
    for sn, sp in (graph.get("speculative") or {}).items():
        t = graph["nodes"][sp["target"]]
        if "planned" in (t["status"], sp.get("status")) or sp["mode"] != "draft" or sp["target"] not in metas: continue  # planned speculation loads nothing
        d = models[sp["draft"]]; dp = os.path.expanduser(d["gguf"])
        if not os.path.isfile(dp): errs.append(f"speculative.{sn}: draft file not found: {dp}"); continue
        dmeta = gguf_meta(dp)
        tv, dv = vocab(metas[sp["target"]]), vocab(dmeta)
        if tv != dv or None in tv:
            errs.append(f"speculative.{sn}: tokenizer/vocab mismatch target {tv[:2]} hash {str(tv[2])[:12]} vs draft {dv[:2]} hash {str(dv[2])[:12]}")
        dctx = sp.get("draft_ctx", t["ctx"])
        dkv = kv_mib(dmeta, dmeta.get("general.architecture"), dctx, sp.get("draft_kv_type", t["kv_type"])) or 0
        totals[t["host"]] = totals.get(t["host"], 0.0) + os.path.getsize(dp) / 2**20 + dkv  # draft weights + its KV
    def _android_host(h):
        hh = hosts.get(h) or {}
        hos = str(hh.get("os") or "").lower()
        return hh.get("kind") == "phone" or hos.startswith("android")

    def _swap_rich_host(h):
        """Non-Android host that declares swap budget on an active node, or measured swap >= 32 GiB."""
        if _android_host(h):
            return False
        for _n, nd in graph["nodes"].items():
            if nd.get("host") != h or nd.get("status") == "planned":
                continue
            if int(nd.get("swap_budget_mib") or 0) >= 8192:
                return True
        # Live swap only describes this machine: use it for the local graph host alone
        # (angel's swap must not make miryam look swap-rich).
        if local is not None and h != local:
            return False
        have = host_swap_total_mib()
        if have is not None and have >= 32768:
            return True
        return False

    for h, total in totals.items():
        # RAM safety (docs/ram-safety.md). Android phones stay hard-fail on overcommit.
        # Swap-rich desktops/laptops/servers (angel-class): overcommit and tight margins are
        # advisory — software VVRAM / large swap is the intended path.
        ram = hosts[h]["ram_mib"]
        reserve = hosts[h].get("reserve_ram_mib") or 0
        soft = _swap_rich_host(h)
        if total > ram:
            msg = f"hosts.{h}: estimated RAM {total:.0f} MiB exceeds physical ram_mib {ram} MiB (overcommit)"
            if soft:
                WARNINGS.append(msg + " (swap-rich non-Android: advisory; see docs/vvram-ssd/LAYER.md)")
            else:
                errs.append(msg)
            if not soft:
                continue
        if total + reserve > ram:
            WARNINGS.append(
                f"hosts.{h}: estimated RAM {total:.0f} MiB + provisional reserve {reserve} MiB exceeds ram_mib {ram} MiB "
                f"(guidance, not a hard limit; see docs/ram-safety.md)")
        free_after = ram - total
        # Small-host floor: skip noise on swap-rich angel-class; keep for phones / tight hosts
        if (not soft) and ram < 8192 and free_after < 2048:
            WARNINGS.append(
                f"hosts.{h}: estimated free after nodes {free_after:.0f} MiB < 2048 MiB provisional floor "
                f"on host with ram_mib {ram} < 8192 (guidance; see docs/ram-safety.md)")
    errs += check_vvram_policy(graph, metas=metas)
    return errs, totals

# Vulkan llama.cpp builds allocate ~1.83 GB of Vulkan host buffers in shmem even with -ngl 0
# (miryam, b11374), which counts against the memcap scope and stalls the server. With no GPU
# layers, hide the Vulkan devices. An explicit GGML_VK_VISIBLE_DEVICES in env wins.
def server_env(graph, name, env=None):
    env = dict(os.environ if env is None else env)
    if graph["nodes"][name]["offload"]["ngl"] == 0 and "GGML_VK_VISIBLE_DEVICES" not in env:
        env["GGML_VK_VISIBLE_DEVICES"] = ""
    return env

def merge_args(base, extra):
    """base argv plus extra: a flag already in base keeps base's value unless extra is a
    model REQUIRED value for -b/-ub (base has none of those)."""
    have = set(x for x in base if x.startswith("-"))
    out, i = list(base), 0
    alias = {"--ctx-size": "-c", "--parallel": "-np", "--embedding": "--embeddings", "--n-gpu-layers": "-ngl", "--gpu-layers": "-ngl"}
    while i < len(extra):
        f = extra[i]
        v = extra[i + 1] if i + 1 < len(extra) and not (extra[i + 1].startswith("-") and not extra[i + 1][1:2].isdigit()) else None
        if f not in have and alias.get(f) not in have:
            out.append(f)
            if v is not None: out.append(v)
        i += 2 if v is not None else 1
    return out

def explain(graph, name):
    import model_db, model_params as mp
    n = graph["nodes"][name]; m = graph["models"][n["model"]]
    e = model_db.load(m["db"]) if m.get("db") else None
    if e is None: return [f"nodes.{name}: no model database entry"]
    rp = e.get("required_params") or {}
    out = [f"node {name}: {e['id']} ({rp.get('kind')}), native ctx {rp.get('native_ctx')} ({rp.get('native_ctx_source')}), node ctx {n.get('ctx')} x {n.get('parallel')} slot(s)"]
    for it in rp.get("items") or []:
        ov = model_db._ovr(n.get("override_reasons") or {}, it["flag"])
        out.append(f"  {it['class']:<11} {it['flag']} {it.get('value') or ''}  <- {it['source']}" + (f"  [override: {ov}]" if ov else "") + ("  [client]" if it.get("client") else ""))
    _, errs, notes = model_db.node_params(graph, name, e)
    out += [f"  ERROR {x}" for x in errs] + [f"  note: {x}" for x in notes]
    return out


def slot_save_dir(n, name):
    """Directory for llama-server --slot-save-path: node.spill_path or ~/.cache/familia/slots/<node>."""
    raw = n.get("spill_path") or f"~/.cache/familia/slots/{name}"
    return os.path.expanduser(raw)

def vvram_spill_configured(n):
    import ctx_vvram
    return ctx_vvram.vvram_spill_configured(n)

def admit_peak_mib(graph, name):
    import ctx_vvram
    return ctx_vvram.admit_peak_mib(graph, name, gguf_meta=gguf_meta, kv_mib=kv_mib)

def check_vvram_policy(graph, metas=None):
    import ctx_vvram
    return ctx_vvram.check_vvram_policy(graph, metas=metas, gguf_meta=gguf_meta, kv_mib=kv_mib)

def host_swap_total_mib():
    """Total swap MiB on this machine, or None if unknown. FreeBSD swapinfo -k; Linux /proc/swaps."""
    try:
        if os.path.exists("/proc/swaps"):
            total_kib = 0
            with open("/proc/swaps") as f:
                next(f, None)
                for line in f:
                    parts = line.split()
                    if len(parts) >= 3 and parts[2].isdigit():
                        total_kib += int(parts[2])
            return total_kib // 1024
        import subprocess
        r = subprocess.run(["swapinfo", "-k"], capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return None
        total = 0
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] != "Device" and parts[1].isdigit():
                total += int(parts[1])
        return total // 1024 if total else 0
    except Exception:
        return None

def check_swap_budgets(graph, host=None):
    """Errors when an active local node's swap_budget_mib exceeds *this* machine's swap.

    Host-local only: budgets for other graph hosts are ignored here (run on angel for angel).
    If --host names a different host than the OS/local_names match, that scope is skipped.
    """
    errs = []
    try:
        from start_graph import select_host, StartupError
        local = select_host(graph)
    except Exception:
        local = None
    scope = host if host is not None else local
    if scope is None:
        errs.append("--check-swap: cannot resolve local graph host (set --host or hosts.*.local_names)")
        return errs
    if local is not None and scope != local:
        # Measuring this box's swap against angel's budget would false-fail.
        WARNINGS.append(
            f"--check-swap skipped: this machine is graph host {local!r}, not {scope!r}; "
            f"run validate_graph --check-swap on {scope}"
        )
        return errs
    need = {}  # host -> (budget, [node names])
    for name, n in (graph.get("nodes") or {}).items():
        if n.get("status") != "active" or n.get("host") != scope:
            continue
        b = n.get("swap_budget_mib")
        if b is None:
            continue
        h = n.get("host")
        budget, names = need.get(h, (0, []))
        need[h] = (max(budget, int(b)), names + [name])
    if not need:
        return errs
    have = host_swap_total_mib()
    if have is None:
        errs.append("--check-swap: could not read host swap (swapinfo /proc/swaps)")
        return errs
    for h, (budget, names) in need.items():
        if have < budget:
            errs.append(
                f"host {h!r}: swap total {have} MiB < swap_budget_mib {budget} "
                f"(nodes: {', '.join(names)}; see docs/vvram-ssd/LAYER.md)"
            )
    return errs

# Per-TYPE --tools policy (DUP-04, CFG-SPEC-TOOLS-002). TYPE = node.role else models[model].role.
# chat/general: read-only introspection; coder: full agentic set; embed/decision/reasoning: none;
# guardian/pentest: current pentest-policy mode (empty allow-list now). node.server_tools overrides.
# "none" is represented as [] and maps to omitting --tools: llama.cpp has no "none" token and is
# tools-disabled by default (docs/config/routing-spec.md CFG-SPEC-TOOLS).
# Capability-based tools default (CFG-SPEC-TOOLS-007..010). Any node whose model can use tools
# gets "all" by default; a node whose tool use goes through nexus/graph routing (`tool_route:
# <node>`) is tool-capable via routing. guardian/pentest/defender always fail closed (TOOLS-005);
# a present `server_tools` key is authoritative (TOOLS-006). "none" is [] -> no --tools flag.
FAIL_CLOSED_TYPES = ("guardian", "pentest", "defender")
# TYPE presumption when neither node nor model declares `tool_capable`.
TOOL_CAPABLE_BY_TYPE = {"coder": True, "chat": True, "general": True, "reasoning": True,
                        "embed": False, "decision": False, "vision": False, "diffusion": False}
# Back-compat name: per-TYPE default expressed as a policy (derived from capability).
TOOL_POLICY_BY_TYPE = {t: ("all" if c else []) for t, c in TOOL_CAPABLE_BY_TYPE.items()}
TOOL_POLICY_BY_TYPE.update({t: [] for t in FAIL_CLOSED_TYPES})


def node_type(graph, name):
    n = graph["nodes"][name]
    if n.get("role"):
        return n["role"]
    m = (graph.get("models") or {}).get(n.get("model")) or {}
    return m.get("role")


def _loopback(bind):
    """True only for a loopback bind: localhost (any case), 127/8, ::1, [::1],
    ::ffff:127.x. Anything unparseable is NOT loopback (fail-safe)."""
    import ipaddress
    b = str(bind or "").strip()
    if b.lower() == "localhost":
        return True
    if b.startswith("[") and b.endswith("]"):
        b = b[1:-1]
    try:
        ip = ipaddress.ip_address(b)
    except ValueError:
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    return (mapped or ip).is_loopback


def tool_capable(graph, name):
    """Direct capability: node.tool_capable > model.tool_calls > TYPE presumption."""
    n = graph["nodes"][name]
    if isinstance(n.get("tool_capable"), bool):
        return n["tool_capable"]
    m = (graph.get("models") or {}).get(n.get("model")) or {}
    if isinstance(m.get("tool_calls"), bool):
        return m["tool_calls"]
    return TOOL_CAPABLE_BY_TYPE.get(node_type(graph, name), False)


def tool_route(graph, name):
    """Validated nexus tool target for `name`, or None. Comes only from graph config: the target
    must be an existing, directly tool-capable, non-fail-closed node that is not itself routed."""
    nodes = graph.get("nodes") or {}
    t = (nodes.get(name) or {}).get("tool_route")
    if not isinstance(t, str) or t == name or t not in nodes:
        return None
    if node_type(graph, t) in FAIL_CLOSED_TYPES or nodes[t].get("tool_route"):
        return None
    if not tool_capable(graph, t) or tool_policy(graph, t) == []:
        return None
    return t


def tool_policy(graph, name):
    """Tools grant for a node: "all", a list of tool names, or [] (no tools). Every grant goes
    through here (launcher, nexus routing).
    - guardian/pentest/defender fail closed to [] regardless of override or route (TOOLS-005).
    - A present `server_tools` key is authoritative: "all"/non-empty list verbatim; [], none,
      false, "" are an explicit opt-out, also via nexus (TOOLS-006/009).
    - Otherwise capability: directly tool-capable on a loopback bind -> "all" (TOOLS-007/008);
      tool-capable via a validated `tool_route` -> the target's tool_policy (TOOLS-009); else []."""
    n = graph["nodes"][name]
    if node_type(graph, name) in FAIL_CLOSED_TYPES:
        return []
    if "server_tools" in n:
        st = n.get("server_tools")
        if st == "all":
            return "all"
        if isinstance(st, list) and st:
            return st
        return []
    if tool_capable(graph, name) and _loopback(n.get("bind")):
        return "all"
    t = tool_route(graph, name) if n.get("tool_route") else None
    if t:
        return tool_policy(graph, t)  # routed grant = the target's own validated grant
    return []


def tools_argv(graph, name):
    """argv fragment for --tools; [] when the explicit decision is no tools."""
    pol = tool_policy(graph, name)
    n = graph["nodes"][name]
    # Routed-only nodes execute tools on their nexus target, not via their own --tools.
    if pol and "server_tools" not in n and not tool_capable(graph, name):
        return []
    if pol == "all":
        return ["--tools", "all"]
    if isinstance(pol, list) and pol:
        return ["--tools", ",".join(pol)]
    return []


def server_args(graph, name):
    n = graph["nodes"][name]
    kind = (graph["runtimes"].get(n["runtime"]) or {}).get("kind", "llama-server")
    if kind != "llama-server":
        raise SystemExit(f"graph: ERROR: runtime kind {kind!r} is not a llama-server; it has no server args (LittleBit has no serving runtime yet)")
    m = graph["models"][n["model"]]
    a = ["-m", os.path.expanduser(m["gguf"]), "--host", n["bind"], "--port", str(n["port"]),
         "-c", str(n["ctx"]), "-np", str(n["parallel"]), "-ctk", n["kv_type"], "-ctv", n["kv_type"],
         "-ngl", str(n["offload"]["ngl"]), "--jinja"]
    if n["offload"]["ngl"]: a += ["-sm", n["offload"]["split"], "-mg", str(n["offload"]["main_gpu"])]
    if n["flash_attn"]: a += ["-fa", "on"]
    if n.get("threads"): a += ["-t", str(n["threads"])]
    if n.get("load_mode"): a += ["-lm", n["load_mode"]]
    if n.get("slot_save") or n.get("spill_path"):  # #85 + SSD/VVRAM spill (docs/vvram-ssd/LAYER.md)
        d = slot_save_dir(n, name); os.makedirs(d, exist_ok=True)
        a += ["--slot-save-path", d]
    names = sorted(al for al, x in graph["aliases"].items() if x["node"] == name)
    if names: a += ["--alias", names[0]]
    a += ["--cache-ram", str(n["cache_ram_mib"])]
    # llama-ui Server Tools: /tools is feature_disabled (403) unless --tools is set at launch.
    # DUP-04/CFG-SPEC-TOOLS: explicit per-TYPE decision on every launch (override via server_tools).
    a += tools_argv(graph, name)
    # Model parameters (#51): REQUIRED + RECOMMENDED from the model database (cards, configs,
    # GGUF), node.sampling / override_reasons applied. A REQUIRED one that cannot be met is fatal.
    import model_db
    e = model_db.load(m["db"]) if m.get("db") else None
    if e is None:
        raise SystemExit(f"graph: ERROR: nodes.{name}: model {n['model']} has no model database entry; its required parameters are unknown")
    extra, errs, _ = model_db.node_params(graph, name, e)
    if errs:
        raise SystemExit("\n".join(f"graph: ERROR: nodes.{name}: {x}" for x in errs))
    a = merge_args(a, extra)
    import model_params as mp
    _, build = model_db.runtime_build(graph, n)
    reasons = n.get("override_reasons") or {}
    ovr = {it["flag"].lstrip("-"): True for it in (e.get("required_params") or {}).get("items") or []
           if it["class"] == mp.REC and model_db._ovr(reasons, it["flag"])}
    for k in model_db.launch_sampling(e, n) if (e.get("required_params") or {}).get("kind") == "chat" else {}:
        ovr[model_db.SAMPLING_FLAGS[k].lstrip("-")] = True       # node.sampling (checked by check_graph)
    miss = mp.missing_required(e["required_params"], a, n.get("ctx"), n.get("parallel") or 1, build, ovr)
    if miss:
        raise SystemExit("\n".join(f"graph: ERROR: nodes.{name}: {x}" for x in miss))
    # Speculative flags verified against b11374/b11539 --help; --draft-max/--draft-min were removed upstream.
    for sp in (graph.get("speculative") or {}).values():
        if sp["target"] != name or sp["status"] == "planned": continue
        if sp["mode"] == "draft":
            a += ["-md", os.path.expanduser(graph["models"][sp["draft"]]["gguf"]), "--spec-type", sp.get("spec_type", "draft-simple"),
                  "--spec-draft-n-max", str(sp["draft_max"]), "--spec-draft-n-min", str(sp["draft_min"]),
                  "--spec-draft-p-min", str(sp["p_min"]), "-ngld", str(sp.get("draft_ngl", 0))]
            if "draft_kv_type" in sp: a += ["-ctkd", sp["draft_kv_type"], "-ctvd", sp["draft_kv_type"]]
        else:
            a += ["--spec-type", sp["spec_type"]]
    r = graph["runtimes"][n["runtime"]]
    if "bin" in r:
        a = [os.path.join(os.path.dirname(os.path.abspath(graph.get("_path", "graph.yaml"))), r["bin"])] + a
    return a

USAGE = __doc__.split("\n\n")[1]

def parse_argv(argv):
    """-> dict of options; SystemExit(2) on an unknown flag or a missing value.

    A single positional *.yaml / *.yml path is accepted as --graph (with a one-line
    deprecation note) so older callers (with-fleet.sh, installers) keep working (#74).
    """
    o = {"graph": "graph.yaml", "host": None, "no_files": False, "verify_sha": False, "check_runtimes": False, "check_swap": False, "args": None, "explain": None}
    graph_set = False
    positional = None
    it = iter(argv)
    for x in it:
        if x in ("-h", "--help"): print(__doc__.strip()); raise SystemExit(0)
        elif x in ("--graph", "--host", "--args", "--explain"):
            v = next(it, None)
            if v is None or v.startswith("-"): print(f"validate_graph.py: {x} needs a value\n{USAGE}", file=sys.stderr); raise SystemExit(2)
            o[x[2:]] = v
            if x == "--graph":
                graph_set = True
        elif x in ("--no-files", "--verify-sha", "--check-runtimes", "--check-swap"): o[x[2:].replace("-", "_")] = True
        elif not x.startswith("-") and positional is None and (x.endswith(".yaml") or x.endswith(".yml")):
            positional = x
        else: print(f"validate_graph.py: unknown argument {x!r}\n{USAGE}", file=sys.stderr); raise SystemExit(2)
    if positional is not None:
        if graph_set and o["graph"] != positional:
            print("validate_graph.py: both --graph and a positional path were given; using --graph %s" % o["graph"], file=sys.stderr)
        elif not graph_set:
            o["graph"] = positional
            print("validate_graph.py: note: positional graph path is deprecated; prefer --graph %s" % positional, file=sys.stderr)
    return o

def main(argv):
    o = parse_argv(argv)
    path = o["graph"]
    try:
        raw_text = open(path, encoding="utf-8").read()
        graph = load(path); graph["_path"] = path
    except yaml.YAMLError as e:
        print(f"graph: ERROR: {e}", file=sys.stderr); return 1
    except OSError as e:
        print(f"graph: ERROR: {e}", file=sys.stderr); return 1
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import hosts_overlay
    # Privacy lint runs on the tracked file *before* overlay merge (#104).
    privacy_errs = hosts_overlay.privacy_lint_graph(graph, path_label=path, raw_text=raw_text)
    hosts_overlay.merge_connection_overlay(graph, graph_path=path)
    if o["host"] and o["host"] not in graph.get("hosts", {}):
        print(f"graph: ERROR: no host {o['host']!r}", file=sys.stderr); return 1
    errs, totals = validate(graph, check_files=not o["no_files"], host=o["host"])
    errs = list(privacy_errs) + list(errs)
    from transport_graph import validate_transports
    errs += validate_transports(graph)  # meshes: (ssh nexus / bittorrent), #22
    if o["check_swap"]:
        errs += check_swap_budgets(graph, host=o["host"])
    for w in WARNINGS: print(f"graph: WARNING: {w}", file=sys.stderr)
    for e in errs: print(f"graph: ERROR: {e}", file=sys.stderr)
    if errs: return 1
    for k in ("args", "explain"):
        if o[k] and o[k] not in graph["nodes"]:
            print(f"graph: ERROR: no node {o[k]!r}", file=sys.stderr); return 1
    if o["args"] and o["host"] and graph["nodes"][o["args"]]["host"] != o["host"]:
        print(f"graph: ERROR: node {o['args']!r} is on host {graph['nodes'][o['args']]['host']!r}, not {o['host']!r}", file=sys.stderr)
        return 1
    if o["args"]:
        print(" ".join(server_args(graph, o["args"]))); return 0
    if o["explain"]:
        print("\n".join(explain(graph, o["explain"]))); return 0
    try:  # model registry evidence (docs/model-registry.md): warn only, never fail
        import registry as _reg
        for w in _reg.graph_warnings(graph): print(f"graph: WARNING: {w}", file=sys.stderr)
    except Exception as e: print(f"graph: WARNING: registry check skipped: {e}", file=sys.stderr)
    est = ", ".join(f"{h} est. {t:.0f} MiB" for h, t in totals.items()) or "file checks skipped"
    print(f"graph: OK ({len(graph['nodes'])} node(s); {est})")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
