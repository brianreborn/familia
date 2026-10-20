#!/usr/bin/env python3
"""Termux-side adapter for phone system agents (#80). No root: everything goes through
Shizuku's rish shell (uid 2000). Stdlib only, so it runs on Termux's python.

usage: system_agent.py probe [--json] [--dry-run]
       system_agent.py consent --provider gemini|bixby (--grant | --revoke | --show)
       system_agent.py open --provider gemini|bixby [--dry-run]
       system_agent.py ask --provider gemini --text TEXT [--timeout S] [--json] [--dry-run] [--yes-cloud]
       system_agent.py -h | --help

probe    report Shizuku state (running / stopped / stopped-after-reboot / absent) and which
         assistant apps are present; writes ~/.cache/familia/system-agent.json for familia-monitor
consent  record or withdraw standing consent to send text to that provider's cloud
open     bring the assistant app to the front (nothing is sent)
ask      gemini/app only: hand TEXT to the Gemini app (ACTION_SEND), press its Send button and
         read the reply off the screen with uiautomator. CLOUD: TEXT goes to Google. Asks first
         unless consent was granted or --yes-cloud is given.
--dry-run prints the rish commands and sends nothing.

Not wired (documented, see docs/system-agents.md): bixby ask (no documented text entry),
gemini nano (needs a companion app built on ML Kit GenAI; familia ships none).
Live testing on a real phone is PENDING; UI reading is a heuristic until then.
Exit codes: 0 ok, 1 failed, 2 usage, 3 no consent, 4 Shizuku not running, 5 not available.
"""
import json, os, re, shlex, subprocess, sys, time

HOME = os.path.expanduser("~")
STATE = os.environ.get("FAMILIA_SYSTEM_AGENT_STATE") or os.path.join(HOME, ".cache", "familia", "system-agent.json")
CONSENT = os.environ.get("FAMILIA_SYSTEM_AGENT_CONSENT") or os.path.join(HOME, ".config", "familia", "system-agent-consent.json")
GEMINI_PKG = "com.google.android.apps.bard"
AICORE_PKG = "com.google.android.aicore"
DUMP = "/data/local/tmp/familia-ui.xml"
MAX_TEXT = 4000
CLOUD_WHAT = {"gemini": "your text goes to Google's Gemini service under the phone's Google account",
              "bixby": "your request goes to Samsung (and Perplexity for web answers)"}


class Fail(Exception):
    def __init__(self, msg, code=1):
        super().__init__(msg); self.code = code


def rish_path():
    for p in (os.environ.get("FAMILIA_RISH"), os.path.join(os.environ.get("PREFIX", "/nonexistent"), "bin", "rish"),
              os.path.join(HOME, "rish")):
        if p and os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


class Shell:
    """Runs commands as the Shizuku shell user; dry_run records them instead."""
    def __init__(self, dry_run=False):
        self.dry, self.log, self.rish = dry_run, [], rish_path()

    def run(self, cmd, timeout=20, check=True):
        self.log.append(cmd)
        if self.dry:
            print("rish -c " + shlex.quote(cmd)); return ""
        if not self.rish:
            raise Fail("rish not found: export it from the Shizuku app (Use Shizuku in terminal apps) into ~/ or $PREFIX/bin", 4)
        env = dict(os.environ); env.setdefault("RISH_APPLICATION_ID", "com.termux")
        try:
            p = subprocess.run([self.rish, "-c", cmd], capture_output=True, text=True, timeout=timeout, env=env)
        except subprocess.TimeoutExpired:
            raise Fail(f"Shizuku command timed out after {timeout}s", 4)
        if check and p.returncode != 0:
            raise Fail(f"Shizuku command failed ({p.returncode}): {(p.stderr or p.stdout).strip()[:200]}", 4 if "Shizuku" in (p.stderr or "") else 1)
        return p.stdout


def boot_id():
    try:
        with open("/proc/sys/kernel/random/boot_id") as f: return f.read().strip()
    except OSError:
        return None


def read_json(path, default):
    try:
        with open(path) as f: return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(data, f, indent=1)
    os.replace(tmp, path)


def shizuku_state(sh):
    """-> (state, uid). running = Shizuku via ADB (uid 2000) or root (uid 0)."""
    if not sh.rish and not sh.dry:
        return "absent", None
    try:
        out = sh.run("id", timeout=8)
    except Fail:
        prev = read_json(STATE, {})
        b = boot_id()
        if prev.get("shizuku") in ("running", "stopped-after-reboot") and prev.get("boot_id") and b and prev["boot_id"] != b:
            return "stopped-after-reboot", None
        return "stopped", None
    m = re.search(r"uid=(\d+)", out or "")
    return ("running", int(m.group(1))) if m else (("unknown", None) if sh.dry else ("stopped", None))


def packages(sh):
    out = sh.run("pm list packages", timeout=20)
    return sorted(l.split(":", 1)[1].strip() for l in (out or "").splitlines() if l.startswith("package:"))


def bixby_pkgs(pkgs):
    return [p for p in pkgs if "bixby" in p.lower()]


def probe(sh):
    st, uid = shizuku_state(sh)
    res = {"time": int(time.time()), "boot_id": boot_id(), "shizuku": st, "uid": uid,
           "providers": {}, "live_tested": False}
    if st == "running":
        pk = packages(sh)
        sdk = (sh.run("getprop ro.build.version.sdk", timeout=8) or "").strip()
        res["sdk"] = int(sdk) if sdk.isdigit() else None
        res["providers"] = {"gemini": {"app": GEMINI_PKG in pk, "aicore": AICORE_PKG in pk, "nano_companion": False},
                            "bixby": {"app": bool(bixby_pkgs(pk))}}
    if st == "stopped-after-reboot":
        res["hint"] = "Shizuku stops at every reboot without root: open Shizuku and press Start (wireless debugging)"
    elif st == "absent":
        res["hint"] = "Shizuku/rish not set up; see docs/system-agents.md"
    if not sh.dry:
        write_json(STATE, res)
    return res


def consent_ok(provider):
    return bool(read_json(CONSENT, {}).get(provider, {}).get("granted"))


def ask_consent(provider, yes_cloud):
    if yes_cloud or consent_ok(provider):
        return
    if not sys.stdin.isatty():
        raise Fail(f"no consent for cloud calls to {provider}: {CLOUD_WHAT[provider]}. "
                   f"Run: system_agent.py consent --provider {provider} --grant (or pass --yes-cloud)", 3)
    sys.stderr.write(f"This is a CLOUD call: {CLOUD_WHAT[provider]}. Send it? [y/N] ")
    if sys.stdin.readline().strip().lower() not in ("y", "yes"):
        raise Fail("not sent (no consent)", 3)


def ui_dump(sh):
    out = sh.run(f"uiautomator dump {DUMP} >/dev/null && cat {DUMP}; rm -f {DUMP}", timeout=30)
    return out or ""


NODE_RE = re.compile(r"<node\b([^>]*)>")
ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def nodes(xml):
    out = []
    for m in NODE_RE.finditer(xml):
        a = dict(ATTR_RE.findall(m.group(1)))
        for k in ("text", "content-desc"):
            a[k] = (a.get(k) or "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#10;", "\n")
        out.append(a)
    return out


def center(bounds):
    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds or "")
    if not m: return None
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1 + x2) // 2, (y1 + y2) // 2


def find_send(ns):
    for a in ns:
        label = (a.get("content-desc") or a.get("text") or "").strip().lower()
        if label in ("send", "send message", "submit") and a.get("package", GEMINI_PKG) == GEMINI_PKG:
            c = center(a.get("bounds"))
            if c: return c
    return None


def reply_after(ns, prompt):
    """Texts after the last node that shows our prompt (heuristic; verify live)."""
    texts = [a["text"] for a in ns if a.get("text") and a.get("package", GEMINI_PKG) == GEMINI_PKG]
    p = prompt.strip()[:80]
    idx = max((i for i, t in enumerate(texts) if p and p in t), default=None)
    if idx is None: return ""
    return "\n".join(t for t in texts[idx + 1:] if t.strip()).strip()


def check_text(t):
    if not t or not t.strip(): raise Fail("--text is empty", 2)
    if len(t) > MAX_TEXT: raise Fail(f"--text is longer than {MAX_TEXT} characters", 2)
    if any(ord(c) < 32 and c not in "\n\t" for c in t): raise Fail("--text has control characters", 2)


def ask(sh, provider, backend, text, timeout, yes_cloud):
    if provider == "bixby":
        raise Fail("bixby ask is not wired: Samsung documents no text entry for Bixby. Use 'open --provider bixby'. "
                   "UI mapping waits for a live test (docs/system-agents.md)", 5)
    if backend == "nano":
        raise Fail("gemini nano needs a companion Android app built on ML Kit GenAI (AICore); familia ships none. "
                   "Supported phones are 2024+ flagships with a locked bootloader (docs/research/phone-system-agents.md)", 5)
    check_text(text)
    if not sh.dry:  # a dry run sends nothing, so it needs no consent
        ask_consent("gemini", yes_cloud)
    sh.run("am start -a android.intent.action.SEND -t text/plain --es android.intent.extra.TEXT "
           + shlex.quote(text) + f" -p {GEMINI_PKG} -f 0x10000000")
    if sh.dry:
        sh.run("uiautomator dump ... (find the Send button)"); sh.run("input tap X Y"); sh.run("uiautomator dump ... (read reply)")
        return {"provider": "gemini", "backend": "app", "cloud": True, "reply": None, "dry_run": True}
    time.sleep(2.0)
    pos = None
    for _ in range(5):
        pos = find_send(nodes(ui_dump(sh)))
        if pos: break
        time.sleep(1.0)
    if not pos:
        raise Fail("could not find Gemini's Send button on screen (is the phone unlocked?). Nothing was sent.", 1)
    sh.run(f"input tap {pos[0]} {pos[1]}")
    last, stable, t0 = None, 0, time.time()
    while time.time() - t0 < timeout:
        time.sleep(2.0)
        r = reply_after(nodes(ui_dump(sh)), text)
        stable = stable + 1 if r and r == last else 0
        last = r
        if stable >= 1: break
    if not last:
        raise Fail(f"sent, but no reply could be read within {timeout}s (open the Gemini app to see it)", 1)
    return {"provider": "gemini", "backend": "app", "cloud": True, "reply": last, "complete": stable >= 1}


def opt(args, name, default=None, flag=False):
    if flag:
        if name in args: args.remove(name); return True
        return False
    if name in args:
        i = args.index(name)
        if i + 1 >= len(args): raise Fail(f"{name} needs a value", 2)
        v = args[i + 1]; del args[i:i + 2]; return v
    return default


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip()); return 0 if argv else 2
    if os.environ.get("FAMILIA_ROLE") == "pentest":
        print("system_agent: refused: pentest roles never use system agents", file=sys.stderr); return 2
    cmd, args = argv[0], list(argv[1:])
    try:
        as_json, dry = opt(args, "--json", flag=True), opt(args, "--dry-run", flag=True)
        provider = opt(args, "--provider")
        if provider is not None and provider not in ("gemini", "bixby"): raise Fail("--provider must be gemini or bixby", 2)
        backend = opt(args, "--backend", "app")
        if backend not in ("app", "nano"): raise Fail("--backend must be app or nano", 2)
        grant, revoke, show = opt(args, "--grant", flag=True), opt(args, "--revoke", flag=True), opt(args, "--show", flag=True)
        yes_cloud = opt(args, "--yes-cloud", flag=True)
        text, timeout = opt(args, "--text"), opt(args, "--timeout", "90")
        if args: raise Fail(f"unknown argument {args[0]!r}", 2)
        try: timeout = max(5, int(timeout))
        except ValueError: raise Fail("--timeout must be seconds", 2)
        sh = Shell(dry)
        if cmd == "probe":
            r = probe(sh)
            print(json.dumps(r) if as_json else f"shizuku: {r['shizuku']}" + (f" (uid {r['uid']})" if r.get("uid") is not None else "")
                  + "".join(f"\n{p}: " + ", ".join(f"{k} {'yes' if v else 'no'}" for k, v in d.items()) for p, d in r["providers"].items())
                  + (f"\nhint: {r['hint']}" if r.get("hint") else ""))
            return 0 if r["shizuku"] == "running" else 4
        if cmd == "consent":
            if not provider: raise Fail("consent needs --provider", 2)
            c = read_json(CONSENT, {})
            if grant or revoke:
                c[provider] = {"granted": bool(grant), "time": int(time.time()), "what": CLOUD_WHAT[provider]}
                write_json(CONSENT, c)
            print(f"{provider}: cloud consent {'granted' if c.get(provider, {}).get('granted') else 'not granted'} ({CLOUD_WHAT[provider]})")
            return 0
        if cmd == "open":
            if not provider: raise Fail("open needs --provider", 2)
            if provider == "gemini":
                sh.run(f"monkey -p {GEMINI_PKG} -c android.intent.category.LAUNCHER 1")
            else:
                pk = ["<bixby package>"] if dry else bixby_pkgs(packages(sh))
                if not pk: raise Fail("no Bixby package on this phone", 5)
                sh.run(f"monkey -p {shlex.quote(pk[0])} -c android.intent.category.LAUNCHER 1")
            return 0
        if cmd == "ask":
            if not provider: raise Fail("ask needs --provider", 2)
            if text is None: raise Fail("ask needs --text", 2)
            r = ask(sh, provider, backend, text, timeout, yes_cloud)
            print(json.dumps(r) if as_json else (r.get("reply") or ""))
            return 0
        raise Fail(f"unknown command {cmd!r} (probe, consent, open, ask)", 2)
    except Fail as e:
        print(f"system_agent: {e}", file=sys.stderr); return e.code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
