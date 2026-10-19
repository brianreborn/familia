#!/usr/bin/env python3
"""model_license.py: show a model's license and get it accepted before its weights are
downloaded or it is launched (familia #51, docs/licenses.md).

  scripts/model_license.py show  ID...                 print the license summary (records nothing)
  scripts/model_license.py check ID...                 exit 0 when every ID's license is accepted
  scripts/model_license.py gate  ID... [--accept-licenses|--yes] [--dry-run]
                                                       check; else print and ask (terminal) or fail
IDs are registry/models entry ids. The summary comes from the entry's license_info: the exact
license id and its source, the full text on disk / link, and the lines of the license or card
that oblige or limit, quoted with file:line. An unknown license is never guessed.

Graph selections (serve.sh, hermes) use scripts/licenses.py gate, which covers every model of
graph.yaml. A model that is not in the graph yet (add-model.sh --fetch, damp runs) is gated
here, per model.
TODO(#51 licenses): switch to `scripts/licenses.py check --models IDS` once licenses.py has
--models; until then acceptance of single models is stored in
.cache/familia/model-license-acceptance.json (licenses.py owns license-acceptance.json).

--accept-licenses / --yes, or FAMILIA_ACCEPT_LICENSES=yes, accepts without a prompt (the summary
is still printed). --dry-run only prints. Exit: 0 accepted, 1 not accepted, 2 usage / no
terminal to ask on."""
import datetime, hashlib, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
ACCEPT_FILE = os.environ.get("FAMILIA_MODEL_LICENSE_ACCEPT_FILE") or os.path.join(ROOT, ".cache", "familia", "model-license-acceptance.json")


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def entry_of(eid, db_dir=None):
    return _load(os.path.join(db_dir or os.path.join(ROOT, "registry", "models"), eid + ".json"))


def info_of(e):
    li = (e or {}).get("license_info") or {}
    if not li:   # an entry from before license_info: what it has, nothing more
        li = {"id": (e or {}).get("license") or "unknown", "id_source": (e or {}).get("license_source"), "unknown":
              not (e or {}).get("license") or (e or {}).get("license") == "unknown"}
    return li


def digest(e):
    """What is accepted: the license id, its summary and the sha256 of every text file."""
    li = info_of(e)
    key = [e.get("id"), li.get("id"), li.get("summary"), sorted((t.get("file"), t.get("sha256")) for t in li.get("texts") or [])]
    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()


def summary(e, out=None):
    out = out or sys.stderr
    li = info_of(e)
    w = out.write
    w("license of %s (%s@%s %s):\n" % (e.get("id"), e.get("repo"), str(e.get("revision"))[:10], e.get("file")))
    w("  id:      %s%s\n" % (li.get("id"), "  (from %s)" % li["id_source"] if li.get("id_source") else ""))
    if li.get("unknown"):
        w("  UNKNOWN: no license is stated by the card, the base model's card or the GGUF header.\n")
        for v in li.get("seen") or []:
            if isinstance(v, dict):
                w("  seen up the base chain (not this model's license): %s (%s)\n" % (v.get("value", v.get("effective")), v.get("source")))
    if li.get("summary") and li.get("summary") != li.get("id"):
        w("  terms:   %s%s\n" % (li["summary"], "  (%s)" % li["summary_source"] if li.get("summary_source") else ""))
    if li.get("link"):
        w("  link:    %s\n" % li["link"])
    for t in li.get("texts") or []:
        w("  text:    %s [%s]%s\n" % (t.get("file"), t.get("what"), " -> " + t["path"] if t.get("path") else ""))
    for q in (li.get("obligations") or [])[:12]:
        w("  says:    \"%s\" (%s)\n" % (q["quote"], q["source"]))
    if li.get("gated"):
        w("  gated:   accept the terms on Hugging Face as well\n")


def accepted(e):
    a = _load(ACCEPT_FILE) or {}
    return (a.get("models") or {}).get(e["id"], {}).get("digest") == digest(e)


def record(e, how):
    a = _load(ACCEPT_FILE) or {}
    a.setdefault("models", {})[e["id"]] = {"digest": digest(e), "license": info_of(e).get("id"), "how": how,
                                           "accepted_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    os.makedirs(os.path.dirname(ACCEPT_FILE), exist_ok=True)
    tmp = ACCEPT_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(a, f, indent=2, sort_keys=True)
    os.replace(tmp, ACCEPT_FILE)


def env_yes():
    return os.environ.get("FAMILIA_ACCEPT_LICENSES", "").lower() in ("1", "yes", "y", "true")


def _ask(prompt):
    if os.environ.get("FAMILIA_NO_TTY", "").lower() in ("1", "yes", "true"):
        return None
    try:
        tty = open("/dev/tty") if not sys.stdin.isatty() and os.path.exists("/dev/tty") else None
    except OSError:
        tty = None
    if not (tty or sys.stdin.isatty()):
        return None
    sys.stderr.write(prompt)
    sys.stderr.flush()
    return (tty or sys.stdin).readline().strip().lower()


def licenses_py_has_models():
    """True once scripts/licenses.py check understands --models (then it is the one gate)."""
    p = os.path.join(HERE, "licenses.py")
    if not os.path.isfile(p):
        return False
    try:
        r = subprocess.run([sys.executable, p, "--help"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return "--models" in (r.stdout + r.stderr)


def gate(entries, yes=False, dry_run=False, what="download or launch"):
    """entries: model database entries. Returns 0 when all are accepted (or dry run), 1 refused, 2 no terminal."""
    yes = yes or env_yes()
    ids = [e["id"] for e in entries]
    if licenses_py_has_models() and not dry_run:
        cmd = [sys.executable, os.path.join(HERE, "licenses.py"), "check", "--models", *ids]
        if subprocess.run(cmd).returncode == 0:
            return 0
        cmd = [sys.executable, os.path.join(HERE, "licenses.py"), "gate", "--models", *ids] + (["--yes"] if yes else [])
        return subprocess.run(cmd).returncode
    todo = [e for e in entries if not accepted(e)]
    for e in (entries if dry_run else todo):
        summary(e)
    if dry_run:
        sys.stderr.write("licenses: dry run, nothing accepted or recorded\n")
        return 0
    if not todo:
        return 0
    if yes:
        for e in todo:
            record(e, "--accept-licenses")
        sys.stderr.write("licenses: accepted (non-interactive) for %s; stored in %s\n" % (", ".join(x["id"] for x in todo), ACCEPT_FILE))
        return 0
    ans = _ask("Type yes to accept the license(s) above and %s, anything else to stop: " % what)
    if ans is None:
        sys.stderr.write("licenses: no terminal to ask on; re-run with --accept-licenses (or FAMILIA_ACCEPT_LICENSES=yes) "
                         "to accept the license(s) above. Nothing was downloaded or started.\n")
        return 2
    if ans not in ("yes", "y"):
        sys.stderr.write("licenses: not accepted. Nothing was downloaded or started.\n")
        return 1
    for e in todo:
        record(e, "interactive")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if argv else 2
    cmd, rest = argv[0], argv[1:]
    yes = dry = False
    ids = []
    for a in rest:
        if a in ("--yes", "-y", "--accept-licenses"):
            yes = True
        elif a == "--dry-run":
            dry = True
        elif a.startswith("-"):
            sys.stderr.write("model_license.py: unknown option %r (see --help)\n" % a)
            return 2
        else:
            ids.append(a)
    if cmd not in ("show", "check", "gate") or not ids:
        sys.stderr.write("model_license.py: usage: show|check|gate ID... (see --help)\n")
        return 2
    ents = []
    for i in ids:
        e = entry_of(i)
        if not e:
            sys.stderr.write("model_license.py: no model database entry %s\n" % i)
            return 2
        ents.append(e)
    if cmd == "show":
        for e in ents:
            summary(e, sys.stdout)
        return 0
    if cmd == "check":
        bad = [e for e in ents if not accepted(e)]
        for e in bad:
            summary(e)
        return 1 if bad else 0
    return gate(ents, yes, dry)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
