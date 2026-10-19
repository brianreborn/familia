#!/usr/bin/env python3
"""licenses.py: show every license your familia selection subjects you to, before anything runs.

Covers the models used by graph.yaml nodes, the skills you enabled, the engines
(llama.cpp builds, hermes-agent, Harness2 when switched on), familia itself, and
the components pinned in pins.txt. Anything custom, restrictive or unknown is
listed first. Your acceptance is stored in .cache/familia/license-acceptance.json
with a hash of the selection and its licenses, so you are asked again only when
something changes.

Usage:
  scripts/licenses.py review [--yes] [--accept-unknown] [--json]   show the list and accept it
  scripts/licenses.py check  [--json] [--quiet]   exit 0 if the current selection is accepted
  scripts/licenses.py gate   [--yes] [--accept-unknown]   check; if needed, review (terminal) or explain
  scripts/licenses.py list   [--json]             show the list only; records nothing
Example:
  scripts/licenses.py review
Options:
  --yes, --accept-licenses   accept without a prompt (the summary is still printed)
  --accept-unknown           also accept items whose license could not be found
  --graph FILE               graph to read (default graph.yaml, or $FAMILIA_GRAPH)
  --add-skill ID             review as if skill ID were also enabled (used by skills.py)
Environment: FAMILIA_ACCEPT_LICENSES=yes is --yes; FAMILIA_ACCEPT_UNKNOWN_LICENSES=yes is --accept-unknown.
Exit codes: 0 accepted; 1 not accepted yet or the selection changed; 2 usage error or no
terminal to ask on; 3 unknown licenses need --accept-unknown.
Stdlib only (PyYAML is used when installed). Docs: docs/licenses.md.
"""
import datetime
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import familia_yaml  # noqa: E402

ACCEPT_FILE = os.environ.get("FAMILIA_LICENSE_ACCEPT_FILE") or os.path.join(ROOT, ".cache", "familia", "license-acceptance.json")
CATALOG = os.path.join(ROOT, "skills", "catalog.json")
REG_MODELS = os.path.join(ROOT, "registry", "models")
LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "License.txt", "license.txt", "LICENCE",
                 "COPYING", "LICENSE-MIT", "LICENSE-APACHE")

# Declared licenses, used only when no local file can be read. Checked on GitHub 2026-10-19.
DECLARED = {
    "llama.cpp": ("MIT", "https://github.com/ggml-org/llama.cpp/blob/master/LICENSE"),
    "hermes-agent": ("MIT", "https://github.com/NousResearch/hermes-agent/blob/main/LICENSE"),
    "harness2": ("Apache-2.0", "https://github.com/google-research/harness2"),
    "code-bootstraps-llama.cpp": ("MIT", "https://github.com/brianreborn/code-bootstraps-llama.cpp/blob/main/LICENSE"),
    "agent-reach": ("MIT", "https://github.com/Panniantong/Agent-Reach/blob/main/LICENSE"),
    "green-agency": ("BSD-3-Clause", "https://github.com/brianreborn/green-agency/blob/main/LICENSE"),
}
NOTES = {
    "green-agentz": "No top-level LICENSE. NOTICE.md says the green-zkillz part is BSD-3-Clause "
                    "(docs/green-zkillz/LICENSE) and declares no license for the rest.",
    "green-roomz": "No LICENSE file in the repo.",
}

ATTENTION_RE = re.compile(r"(acceptable use|prohibited use|use policy|attribution|non-?commercial|not valid in|"
                          r"monthly active|commercial use|advertising materials|acknowledgement|invitation, not)", re.I)
CANON = {"mit": "MIT", "apache-2.0": "Apache-2.0", "apache 2.0": "Apache-2.0", "bsd-3-clause": "BSD-3-Clause",
         "bsd-2-clause": "BSD-2-Clause", "isc": "ISC", "cc-by-nc-4.0": "CC-BY-NC-4.0", "cc-by-4.0": "CC-BY-4.0"}


def canon(lic):
    return CANON.get((lic or "").strip().lower(), lic)


def classify(lic):
    """Return (category, flags) for a license string. category: permissive|copyleft|custom|restrictive|unknown."""
    s = (lic or "").strip().lower()
    flags = []
    if not s or s in ("unknown", "none", "other", "noassertion") or s.startswith("not stated") or s.startswith("unknown"):
        return "unknown", ["unknown"]
    cat = "permissive"
    def worse(c):
        order = ["permissive", "copyleft", "custom", "restrictive"]
        return c if order.index(c) > order.index(cat) else cat
    if re.search(r"\bnc\b|non-?commercial|cc-by-nc", s):
        cat = worse("restrictive"); flags += ["non-commercial", "not OSI-approved"]
    if "proprietary" in s:
        cat = worse("restrictive"); flags += ["proprietary", "not OSI-approved"]
    if "cc-by" in s or "cc by" in s:
        flags.append("attribution required")
        if cat == "permissive":
            cat = "custom"
            flags.append("not OSI-approved")
    if "gemma" in s:
        cat = worse("restrictive"); flags += ["custom terms", "acceptable-use policy", "not OSI-approved"]
    if "lfm" in s or "light-ware" in s or "community license" in s or "llama" in s.replace("llama.cpp", ""):
        cat = worse("custom"); flags += ["custom terms", "not OSI-approved"]
    if "not valid in" in s or "european union" in s:
        cat = worse("restrictive"); flags.append("region-limited")
    if "monthly active" in s:
        flags.append("user-count limit")
    if "4-clause" in s or "light-ware" in s:
        flags.append("advertising/attribution clause")
    if re.search(r"\b(a?gpl|lgpl|mpl)", s):
        cat = worse("copyleft"); flags.append("copyleft")
    if cat == "permissive" and not re.search(r"\b(mit|apache|bsd|isc|0bsd|unlicense|zlib)", s):
        return "unknown", ["unrecognized license"]
    out = []
    for f in flags:
        if f not in out:
            out.append(f)
    return cat, out


def sniff_license(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(4000)
    except OSError:
        return None
    h = head.lower()
    for pat, name in ((r"light-ware license", "Light-ware License (BSD 4-clause plus an addition)"),
                      (r"bsd 3-clause|redistributions of source code.*neither the name", "BSD-3-Clause"),
                      (r"\bmit license\b|permission is hereby granted, free of charge", "MIT"),
                      (r"apache license", "Apache-2.0"),
                      (r"gnu affero", "AGPL-3.0"), (r"gnu lesser", "LGPL"), (r"gnu general public", "GPL"),
                      (r"mozilla public", "MPL-2.0"), (r"lfm open license", "lfm1.0"),
                      (r"tencent hy community license", "Tencent HY Community License"),
                      (r"gemma terms of use", "Gemma Terms of Use")):
        if re.search(pat, h, re.S):
            return name
    return None


def excerpts(paths, limit=3):
    out = []
    for p in paths:
        if not p or not os.path.isfile(p):
            continue
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    t = " ".join(line.strip().strip("#*>-").split())
                    if 20 < len(t) and ATTENTION_RE.search(t) and t not in out:
                        out.append(t[:220] + ("..." if len(t) > 220 else ""))
                        if len(out) >= limit:
                            return out
        except OSError:
            continue
    return out


def hf_meta_root():
    r = os.environ.get("FAMILIA_HF_META")
    if r:
        return os.path.expanduser(r)
    gh = os.environ.get("GGUF_HOME") or "~/.local/share/gguf"
    return os.path.join(os.path.expanduser(gh), "hf-meta")


def find_license_file(d):
    if not d or not os.path.isdir(d):
        return None
    for n in LICENSE_NAMES:
        if os.path.isfile(os.path.join(d, n)):
            return os.path.join(d, n)
    return None


def load_json(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def manifest_candidates():
    for base in (os.path.join(ROOT, "code-bootstraps-llama.cpp"), os.path.join(ROOT, "..", "code-bootstraps-llama.cpp")):
        m = load_json(os.path.join(base, "config", "models-manifest.json"))
        if m:
            return m.get("candidates") or []
    return []


def item(kind, ident, used_for, lic, text=None, link=None, notes=None, extra_text=(), source=None):
    lic = canon(lic)
    cat, flags = classify(lic)
    if text is None and cat != "unknown" and source != "declared":
        flags = flags + ["no local copy of the text"]
    it = {"kind": kind, "id": ident, "used_for": used_for, "license": lic or "unknown",
          "category": cat, "flags": flags, "text": text, "link": link, "source": source}
    if notes:
        it["notes"] = notes
    if cat != "permissive":
        ex = excerpts([text] + list(extra_text))
        if ex:
            it["excerpts"] = ex
    return it


def model_items(g):
    out, seen = [], {}
    models = g.get("models") or {}
    mani = {c.get("db_id"): c for c in manifest_candidates() if c.get("db_id")}
    for node, n in (g.get("nodes") or {}).items():
        if not isinstance(n, dict):
            continue
        mname = n.get("model")
        m = models.get(mname) or {}
        db = m.get("db")
        use = f"node {node} on {n.get('host', '?')} ({n.get('status', '?')})"
        if db in seen:
            seen[db]["used_for"] += "; " + use
            continue
        entry = load_json(os.path.join(REG_MODELS, f"{db}.json")) if db else None
        if not entry:
            it = item("model", mname or node, use, "unknown",
                      notes="No model database entry (registry/models/). Add one with scripts/add-model.sh.")
        else:
            snap = (entry.get("snapshot") or {})
            sdir = os.path.join(hf_meta_root(), snap["path"]) if snap.get("path") else None
            lf = find_license_file(sdir)
            card = os.path.join(sdir, "README.md") if sdir else None
            repo, rev = entry.get("repo"), entry.get("revision")
            link = (f"https://huggingface.co/{repo}/blob/{rev}/{os.path.basename(lf)}" if lf and repo and rev
                    else f"https://huggingface.co/{repo}" if repo else None)
            notes = []
            mc = mani.get(db)
            if mc and mc.get("notice"):
                notes.append(f"manifest notice: {mc['notice']}")
            if entry.get("base_model"):
                notes.append(f"base model: {entry['base_model']} (its card may add terms)")
            if not lf:
                notes.append("no LICENSE file in the fetched snapshot; the model card states the license"
                             + ("" if sdir and os.path.isdir(sdir) else " (snapshot not fetched here)"))
            it = item("model", f"{repo} @ {str(rev)[:12]}", use, entry.get("license"),
                      text=lf or (card if card and os.path.isfile(card) else None), link=link,
                      notes="; ".join(notes) or None, extra_text=[card])
            if snap.get("gated"):
                it["flags"].append("gated (you accepted terms on Hugging Face)")
                if it["category"] == "permissive":
                    it["category"] = "restrictive"
        if db:
            seen[db] = it
        out.append(it)
    return out


def load_catalog():
    c = load_json(CATALOG) or {}
    return {s["id"]: s for s in c.get("skills") or [] if isinstance(s, dict) and s.get("id")}


def enabled_skills(g, add=()):
    ids = {}
    for sec in ("agents", "pentests"):
        for name, a in (g.get(sec) or {}).items():
            for sid in (a or {}).get("skills") or []:
                ids.setdefault(sid, []).append(f"{sec[:-1]} {name}")
    for sid in add:
        ids.setdefault(sid, []).append("(about to be enabled)")
    return ids


def skill_items(g, add=()):
    cat, out = load_catalog(), []
    for sid, users in sorted(enabled_skills(g, add).items()):
        s = cat.get(sid)
        if not s:
            out.append(item("skill", sid, ", ".join(users), "unknown", notes="not in skills/catalog.json"))
            continue
        text = None
        if s.get("home") == "green-zkillz" and s.get("status") == "bundled":
            for base in (os.path.join(ROOT, "green-agentz"), os.path.join(ROOT, "..", "green-agentz")):
                p = os.path.join(base, s.get("license_file") or "")
                if os.path.isfile(p):
                    text = p; break
        link = f"{s.get('repo')}/blob/{s.get('commit')}/{s.get('license_file', 'LICENSE')}" if s.get("repo") else None
        out.append(item("skill", f"{sid} ({s.get('status')})", ", ".join(users), s.get("license"),
                        text=text, link=link, notes=s.get("attribution")))
    return out


def harness2_on(g):
    def on(v):
        if isinstance(v, dict):
            v = v.get("mode", "off" if not v.get("enabled") else "propose")
        return isinstance(v, str) and v not in ("off", "")
    if on(g.get("harness2")) or on(g.get("self_improve")):
        return True
    for sec in ("agents", "harnesses"):
        for a in (g.get(sec) or {}).values():
            if isinstance(a, dict) and (on(a.get("self_improve")) or on(a.get("harness2"))):
                return True
    for h in (g.get("harness2") or {}).values() if isinstance(g.get("harness2"), dict) else []:
        if on(h):
            return True
    return False


def engine_items(g):
    out, nodes = [], g.get("nodes") or {}
    used = {}
    for node, n in nodes.items():
        if isinstance(n, dict) and n.get("runtime"):
            used.setdefault(n["runtime"], []).append(node)
    for rname, nodes_ in sorted(used.items()):
        r = (g.get("runtimes") or {}).get(rname) or {}
        kind, use = r.get("kind"), "engine for " + ", ".join(nodes_)
        if kind == "llama-server":
            lic, link = DECLARED["llama.cpp"]
            out.append(item("engine", f"llama.cpp {r.get('build', rname)}", use, lic, link=link, source="declared"))
        elif kind == "drex-dlm":
            p = find_license_file(os.path.join(ROOT, "llama-server__nace-ai__edlm"))
            out.append(item("engine", f"nace-ai/llama.cpp fork ({rname})", use, sniff_license(p) if p else "unknown",
                            text=p, link="https://github.com/nace-ai/llama.cpp",
                            notes=None if p else "fork of llama.cpp (MIT upstream); its own LICENSE is not checked out here"))
        elif kind in ("sm11-legacy", "reference"):
            out.append(item("engine", f"familia {rname}", use, sniff_license(os.path.join(ROOT, "LICENSE")),
                            text=os.path.join(ROOT, "LICENSE"), link="https://github.com/brianreborn/familia/blob/main/LICENSE"))
        else:
            out.append(item("engine", rname, use, "unknown"))
    if any((a or {}).get("kind") == "hermes-agent" for a in (g.get("agents") or {}).values()):
        lic, link = DECLARED["hermes-agent"]
        out.append(item("engine", "hermes-agent (NousResearch)", "agent harness (scripts/hermes.sh)", lic,
                        link=link, source="declared"))
    if harness2_on(g):
        lic, link = DECLARED["harness2"]
        out.append(item("engine", "Harness2 (google-research)", "self-improving harness (switched on)", lic,
                        link=link, source="declared"))
    return out


def component_items():
    out = [item("component", "familia", "this project", sniff_license(os.path.join(ROOT, "LICENSE")) or "unknown",
                text=os.path.join(ROOT, "LICENSE"), link="https://github.com/brianreborn/familia/blob/main/LICENSE")]
    try:
        with open(os.path.join(ROOT, "pins.txt"), encoding="utf-8") as fh:
            rows = [l.rstrip("\n").split("\t") for l in fh]
    except OSError:
        rows = []
    for row in rows:
        if len(row) < 3 or row[0].startswith("#") or row[0] in ("node", "transport") or row[0].startswith("llama-server__"):
            continue
        name, rev, origin = row[0], row[1], row[2]
        role = row[3] if len(row) > 3 else ""
        d = next((x for x in (os.path.join(ROOT, name), os.path.join(ROOT, "..", name)) if os.path.isdir(x)), None)
        lf = find_license_file(d)
        link = origin[:-4] if origin.endswith(".git") else origin
        if lf:
            out.append(item("component", f"{name} @ {rev[:12]}", role, sniff_license(lf) or "unknown",
                            text=lf, link=link, notes=NOTES.get(name)))
        elif name in DECLARED and not d:
            lic, l2 = DECLARED[name]
            out.append(item("component", f"{name} @ {rev[:12]}", role, lic, link=l2, source="declared",
                            notes="not downloaded yet; license as published on GitHub"))
        else:
            out.append(item("component", f"{name} @ {rev[:12]}", role, "unknown", link=link,
                            notes=NOTES.get(name) or ("not downloaded yet" if not d else "no LICENSE file found")))
    return out


def load_graph(path):
    try:
        return familia_yaml.load(path) or {}
    except OSError:
        return {}


def selection(graph_path, add_skills=()):
    g = load_graph(graph_path)
    items = model_items(g) + skill_items(g, add_skills) + engine_items(g) + component_items()
    key = [[i["kind"], i["id"], i["license"]] for i in items]
    digest = hashlib.sha256(json.dumps(sorted(key), sort_keys=True).encode()).hexdigest()
    return items, digest


ATTN_ORDER = {"unknown": 0, "restrictive": 1, "custom": 2, "copyleft": 3, "permissive": 4}
HEAD = {"unknown": "UNKNOWN: no license could be found. Check these by hand before you rely on them.",
        "restrictive": "RESTRICTIVE: limits on use (non-commercial, acceptable-use, region, gated or proprietary).",
        "custom": "CUSTOM: not a standard open-source license. Read the terms.",
        "copyleft": "COPYLEFT: sharing changes may require sharing source.",
        "permissive": "STANDARD OPEN SOURCE (MIT, Apache-2.0, BSD): keep the copyright notice when you redistribute."}


def render(items, digest, out=sys.stdout):
    w = out.write
    w("Licenses for your current familia selection\n")
    w("===========================================\n")
    w("Using this selection means agreeing to every license below. Items that need\n"
      "your attention come first.\n")
    groups = {}
    for i in items:
        groups.setdefault(i["category"], {}).setdefault(i["license"], []).append(i)
    for cat in sorted(groups, key=ATTN_ORDER.get):
        mark = "!" if cat != "permissive" else " "
        w(f"\n{mark} {HEAD[cat]}\n")
        for lic, its in sorted(groups[cat].items()):
            fl = sorted({f for i in its for f in i["flags"] if f not in ("unknown", "no local copy of the text")})
            w(f"  {lic}" + (f"  [{', '.join(fl)}]" if fl and cat != "permissive" else "") + "\n")
            for i in its:
                w(f"    - {i['kind']}: {i['id']}\n")
                if cat != "permissive":
                    w(f"        used for: {i['used_for']}\n")
                    if i.get("text"):
                        w(f"        full text: {i['text']}\n")
                    if i.get("link"):
                        w(f"        link: {i['link']}\n")
                    if i.get("notes"):
                        w(f"        note: {i['notes']}\n")
                    for e in i.get("excerpts", []):
                        w(f"        says: \"{e}\"\n")
    n_att = sum(1 for i in items if i["category"] != "permissive")
    n_unk = sum(1 for i in items if i["category"] == "unknown")
    w(f"\n{len(items)} items, {len({i['license'] for i in items})} licenses; {n_att} need attention, {n_unk} unknown.\n")
    w(f"Selection hash: {digest[:16]}. Full list as JSON: scripts/licenses.py list --json\n")


def accepted(digest, items):
    a = load_json(ACCEPT_FILE) or {}
    if a.get("selection_sha256") != digest:
        return False
    if any(i["category"] == "unknown" for i in items) and not a.get("accepted_unknown"):
        return False
    return True


def record(digest, items, unknown_ok, how):
    os.makedirs(os.path.dirname(ACCEPT_FILE), exist_ok=True)
    data = {"selection_sha256": digest, "accepted_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
            "how": how, "accepted_unknown": bool(unknown_ok),
            "licenses": sorted({i["license"] for i in items}),
            "items": [{k: i[k] for k in ("kind", "id", "license", "category")} for i in items]}
    tmp = ACCEPT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    os.replace(tmp, ACCEPT_FILE)


def env_yes(name):
    return os.environ.get(name, "").lower() in ("1", "yes", "y", "true")


def ask(prompt):
    try:
        tty = (open("/dev/tty") if not sys.stdin.isatty() and os.path.exists("/dev/tty")
               and not env_yes("FAMILIA_NO_TTY") else None)
    except OSError:
        tty = None
    src = tty or sys.stdin
    if not (tty or sys.stdin.isatty()):
        return None
    sys.stderr.write(prompt); sys.stderr.flush()
    ans = src.readline()
    return ans.strip().lower()


def do_review(items, digest, yes, unknown_ok, as_json):
    if as_json:
        print(json.dumps({"selection_sha256": digest, "items": items}, indent=2))
    else:
        render(items, digest)
    sys.stdout.flush()
    has_unknown = any(i["category"] == "unknown" for i in items)
    if yes:
        if has_unknown and not unknown_ok:
            sys.stderr.write("licenses: some licenses are UNKNOWN (listed above). Not accepted.\n"
                             "  Check them, then run again with --accept-unknown (or FAMILIA_ACCEPT_UNKNOWN_LICENSES=yes).\n")
            return 3
        record(digest, items, unknown_ok, "--yes")
        sys.stderr.write("licenses: accepted (non-interactive). Stored in .cache/familia/license-acceptance.json\n")
        return 0
    ans = ask("\nType yes to accept these licenses, anything else to stop: ")
    if ans is None:
        sys.stderr.write("licenses: no terminal to ask on. Re-run with --yes to accept the list above"
                         + (" (plus --accept-unknown for the unknown ones)" if has_unknown else "") + ".\n")
        return 2
    if ans not in ("yes", "y"):
        sys.stderr.write("licenses: not accepted. Nothing was started. Change the selection (models or skills) or review again.\n")
        return 1
    if has_unknown and not unknown_ok:
        ans = ask("Some licenses are UNKNOWN. Type 'accept unknown' to accept them anyway: ")
        if ans != "accept unknown":
            sys.stderr.write("licenses: unknown licenses not accepted. Nothing was started.\n")
            return 3
    record(digest, items, True if has_unknown else unknown_ok, "interactive")
    sys.stderr.write("licenses: accepted. You will be asked again only if the selection or its licenses change.\n")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip()); return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    if cmd not in ("review", "check", "gate", "list"):
        sys.stderr.write(f"licenses: unknown command {cmd!r}. Try: scripts/licenses.py --help\n"); return 2
    graph = os.environ.get("FAMILIA_GRAPH") or os.path.join(ROOT, "graph.yaml")
    yes = env_yes("FAMILIA_ACCEPT_LICENSES"); unknown_ok = env_yes("FAMILIA_ACCEPT_UNKNOWN_LICENSES")
    as_json = quiet = False; add = []
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("--yes", "-y", "--accept-licenses"): yes = True
        elif a == "--accept-unknown": unknown_ok = True
        elif a == "--json": as_json = True
        elif a in ("--quiet", "-q"): quiet = True
        elif a in ("--graph", "--add-skill") and i + 1 < len(rest):
            if a == "--graph": graph = rest[i + 1]
            else: add.append(rest[i + 1])
            i += 1
        elif a in ("-h", "--help"): print(__doc__.strip()); return 0
        else:
            sys.stderr.write(f"licenses: unknown option {a!r}. Try: scripts/licenses.py --help\n"); return 2
        i += 1
    if not os.path.isfile(graph):
        sys.stderr.write(f"licenses: graph not found: {graph}\n"); return 2
    items, digest = selection(graph, add)
    if cmd == "list":
        if as_json: print(json.dumps({"selection_sha256": digest, "items": items}, indent=2))
        else: render(items, digest)
        return 0
    ok = accepted(digest, items)
    if cmd == "check":
        if as_json:
            print(json.dumps({"accepted": ok, "selection_sha256": digest, "items": items}, indent=2))
        elif not ok and not quiet:
            render(items, digest, sys.stderr)
            sys.stderr.write("\nlicenses: this selection's licenses have not been accepted yet (or something changed).\n"
                             "  Next: run scripts/licenses.py review\n")
        return 0 if ok else 1
    if cmd == "gate" and ok:
        return 0
    return do_review(items, digest, yes, unknown_ok, as_json)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
