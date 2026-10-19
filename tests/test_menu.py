"""familia-menu.sh: every item maps to a real command, --dry-run works, no-TTY exits 2, pipes work."""
import os
import re
import shlex
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MENU = os.path.join(ROOT, "familia-menu.sh")
ITEMS_FILE = os.path.join(ROOT, "scripts", "menu-items.txt")
GROUPS = ["Set up", "Skills", "Models", "Agents (hermes)", "Self-improving harness (Harness2)",
          "Test & benchmark", "Hosts", "Advanced: models & graph", "Advanced: agents",
          "Advanced: hosts & benchmarks", "Help"]
INTERNAL_FILE = os.path.join(ROOT, "scripts", "menu-internal.txt")
# --help works but has no usage/example line yet; owned by another job (familia #74).
HELP_NO_EXAMPLE = {"scripts/serve.sh"}


def items():
    out = []
    for line in open(ITEMS_FILE, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        f = line.rstrip("\n").split("|")
        assert len(f) == 7, line
        out.append(dict(zip(("key", "group", "label", "cmd", "gate", "need", "win"), f)))
    return out


def env(**kw):
    e = dict(os.environ, FAMILIA_NO_TTY="1")
    e.pop("FAMILIA_ACCEPT_LICENSES", None)
    e.update(kw)
    return e


def menu(*args, inp=None, **kw):
    return subprocess.run(["bash", MENU, *args], cwd=ROOT, capture_output=True, text=True, env=env(**kw),
                          input=inp, stdin=None if inp is not None else subprocess.DEVNULL, timeout=120)


def need_ok(spec):
    if not spec:
        return True
    if spec.startswith("file:"):
        return os.path.exists(os.path.join(ROOT, spec[5:]))
    path, text = spec[5:].split(":", 1)
    p = os.path.join(ROOT, path)
    return os.path.isfile(p) and text in open(p, encoding="utf-8").read()


def script_of(cmd):
    toks = [t for t in shlex.split(re.sub(r"\{[A-Z]+:[^}]*\}", "X", cmd)) if t not in ("PY", "sh", "bash", "PAGER")]
    t = toks[0].replace("INSTALLER", "install/linux/install.sh")
    return t


def test_groups_in_task_order_and_skills_near_top():
    order = []
    for it in items():
        if it["cmd"] and it["group"] not in order:
            order.append(it["group"])
    assert order == GROUPS


@pytest.mark.parametrize("it", items(), ids=lambda i: i["key"])
def test_item_has_real_command_and_dry_runs(it):
    if not it["cmd"]:  # Windows only
        assert it["win"], it["key"]
        w = it["win"].split()
        ps = next(t for t in w if t.endswith((".ps1", ".bat", ".py")))
        assert os.path.exists(os.path.join(ROOT, ps.replace("\\", "/"))), it["win"]
        r = menu("--run", it["key"], "--dry-run")
        assert r.returncode == 2  # hidden from the POSIX menu
        return
    target = script_of(it["cmd"])
    if need_ok(it["need"]):
        assert os.path.exists(os.path.join(ROOT, target)), f"{it['key']}: {target} does not exist"
    n = len(re.findall(r"\{[A-Z]+:", it["cmd"]))
    r = menu("--run", it["key"], *(["x"] * n), "--dry-run")
    if need_ok(it["need"]):
        assert r.returncode == 0, r.stderr
        assert r.stdout.startswith("[dry-run]")
        if it["gate"] == "lic":
            assert "licenses.py gate" in r.stdout
    else:
        assert r.returncode == 1 and "not available yet" in r.stderr
    if it["win"]:
        w = it["win"].split()
        py = next((t for t in w if t.endswith(".py") or t.endswith(".ps1") or t.endswith(".bat")), None)
        if py and need_ok(it["need"]):
            assert os.path.exists(os.path.join(ROOT, py.replace("\\", "/"))), it["win"]
        assert "&&" not in it["win"], "Windows commands must not use &&"


SCRIPTS = sorted({script_of(i["cmd"]) for i in items() if i["cmd"] and need_ok(i["need"])} - {"QUICKSTART.md", "./familia-menu.sh", "scripts/menu-internal.txt"}
                 | {"./familia-menu.sh", "familia", "with-fleet.sh", "android_multi_start.sh", "watchdog_android.sh",
                    "start-green-roomz.sh", "scripts/run-tests.sh"})


@pytest.mark.parametrize("script", SCRIPTS)
def test_help_everywhere(script):
    path = os.path.join(ROOT, script)
    cmd = ["python3", path] if script.endswith(".py") else ["bash" if open(path).readline().endswith("bash\n") else "sh", path]
    r = subprocess.run(cmd + ["--help"], cwd=ROOT, capture_output=True, text=True, timeout=60, env=env(),
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0, (script, r.stderr[-400:])
    out = (r.stdout + r.stderr).lower()
    if script not in HELP_NO_EXAMPLE:
        assert "usage" in out or "example" in out, script


def internal():
    out = {}
    for line in open(INTERNAL_FILE, encoding="utf-8"):
        if line.strip() and not line.startswith("#"):
            path, reason = line.rstrip("\n").split("|", 1)
            assert reason.strip(), path
            out[path] = reason
    return out


def user_facing_scripts():
    """Every runnable script a user could reach: top-level wrappers, scripts/**, install/**."""
    found = set()
    for f in os.listdir(ROOT):
        p = os.path.join(ROOT, f)
        if os.path.isfile(p) and (f.endswith((".sh", ".bat", ".cmd", ".ps1")) or f in ("familia", "familia-monitor")):
            found.add(f)
    for top in ("scripts", "install"):
        for d, dirs, files in os.walk(os.path.join(ROOT, top)):
            dirs[:] = [x for x in dirs if x != "__pycache__"]
            for f in files:
                p = os.path.join(d, f)
                rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
                if f.endswith((".sh", ".ps1", ".bat", ".cmd")):
                    found.add(rel)
                elif f.endswith(".py") and re.search(r"__name__\s*==\s*['\"]__main__['\"]", open(p, encoding="utf-8", errors="ignore").read()):
                    found.add(rel)
    return found


def menu_text():
    t = []
    for i in items():
        t += [i["cmd"], i["win"].replace("\\", "/")]
    return " ".join(t)


def test_every_user_facing_script_is_in_the_menu():
    text = menu_text()
    alias = {"familia": "./familia-menu.sh", "install/linux/install.sh": "INSTALLER",
             "install/termux/install.sh": "INSTALLER", "familia-monitor": "familia-monitor"}
    allow = internal()
    missing = []
    for s in sorted(user_facing_scripts()):
        if s in allow:
            continue
        if re.search(r"(^|[\s/])" + re.escape(s) + r"(\s|$)", text) or (s in alias and alias[s] in text):
            continue
        missing.append(s)
    assert not missing, ("add these to scripts/menu-items.txt, or to scripts/menu-internal.txt with a reason: "
                         + ", ".join(missing))


def test_internal_list_is_current():
    text = menu_text()
    for path in internal():
        assert os.path.exists(os.path.join(ROOT, path)), f"{path} is listed in menu-internal.txt but no longer exists"
        assert not re.search(r"(^|[\s/])" + re.escape(path) + r"(\s|$)", text), f"{path} is in the menu and in menu-internal.txt"


def test_no_tty_prints_and_exits_2():
    r = menu()
    assert r.returncode == 2
    assert "skills.menu" in r.stdout and "runs: python3 scripts/skills.py menu" in r.stdout
    assert "no terminal" in r.stderr


def test_piped_choices():
    r = menu("--pipe", inp="2\n2\nb\nq\n")
    assert r.returncode == 0, r.stderr
    assert "Running: python3 scripts/skills.py list" in r.stdout
    assert "green-probe" in r.stdout and "license-blocked" in r.stdout
    r = menu("--pipe", inp="9\nx\n2\n7\nq\n")
    assert "isn't one of the choices" in r.stdout


def test_license_gate_blocks_without_terminal(tmp_path):
    r = menu("--run", "hosts.start", FAMILIA_LICENSE_ACCEPT_FILE=str(tmp_path / "a.json"))
    assert r.returncode != 0 and "licenses" in r.stderr.lower()


def test_unknown_key_and_option():
    r = menu("--run", "nope.nope")
    assert r.returncode == 2 and "--list" in r.stderr
    r = menu("--bogus")
    assert r.returncode == 2 and "--help" in r.stderr


def test_familia_entry_point():
    r = subprocess.run(["sh", os.path.join(ROOT, "familia"), "skills", "list"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "green-zkillz" in r.stdout
    r = subprocess.run(["sh", os.path.join(ROOT, "familia"), "bogus"], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 2


def test_no_hardcoded_homes():
    bad = re.compile(r"/home/(green|rcs)\b")
    for d, _, files in os.walk(ROOT):
        if any(p in d for p in ("/.git", "/.cache", "/registry", "/tests/fixtures", "/code-bootstraps-llama.cpp",
                                "/green-", "/agent-reach")):
            continue
        for f in files:
            if f.endswith((".sh", ".py", ".ps1", ".bat", ".cmd", ".txt")) or f == "familia":
                p = os.path.join(d, f)
                try:
                    assert not bad.search(open(p, encoding="utf-8", errors="ignore").read()), p
                except IsADirectoryError:
                    pass


def test_commands_doc_lists_every_item():
    doc = open(os.path.join(ROOT, "docs", "commands.md"), encoding="utf-8").read()
    missing = [i["key"] for i in items() if f"`{i['key']}`" not in doc] + [p for p in internal() if f"`{p}`" not in doc]
    assert not missing, "add to docs/commands.md: " + ", ".join(missing)
