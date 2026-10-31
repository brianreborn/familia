"""familia-menu.sh: every item maps to a real command, --dry-run works, no-TTY exits 2, pipes work."""
import os
import re
import shlex
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MENU = os.path.join(ROOT, "familia-menu.sh")
ITEMS_FILE = os.path.join(ROOT, "scripts", "menu-items.txt")
GROUPS = ["Set up", "Skills", "Reach tools (Agent-Reach)", "Models", "Agents (hermes)",
          "Self-improving harness (Harness2)", "Test & benchmark", "Hosts",
          "Advanced: models & graph", "Advanced: agents", "Advanced: hosts & benchmarks",
          "◆ Proving grounds (graded)", "Help"]
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
    toks = [t for t in shlex.split(re.sub(r"\{[A-Z]+:[^}]*\}", "X", cmd))
            if t not in ("PY", "sh", "bash", "PAGER", "env") and not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", t)]
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


def test_local_host_measure_menu_uses_short_hostname_as_default(tmp_path):
    # Isolate pin state so an existing machine pin cannot change the default.
    state = tmp_path / "state"
    state.mkdir()
    hostname = subprocess.check_output(["hostname"], text=True).strip().split(".", 1)[0].lower()
    r = menu("--pipe", "--dry-run", inp="8\n5\n\nlaptop\nq\n", XDG_STATE_HOME=str(state))
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert f"local graph host [{hostname}]" in r.stderr
    assert f"--name {hostname}" in r.stdout


def test_local_host_measure_menu_prefers_hostname_pin(tmp_path):
    state = tmp_path / "state"
    fam = state / "familia"
    fam.mkdir(parents=True)
    (fam / "hostname").write_text("phone7\n", encoding="utf-8")
    r = menu("--pipe", "--dry-run", inp="8\n5\n\nlaptop\nq\n", XDG_STATE_HOME=str(state))
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert "local graph host [phone7]" in r.stderr
    assert "--name phone7" in r.stdout


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
    assert "GOALS" in r.stdout and "NOT DONE YET" in r.stdout
    assert "skills.menu" in r.stdout and "runs: python3 scripts/skills.py menu" in r.stdout
    assert "no terminal" in r.stderr


def test_guided_paths_are_visible_in_interactive_menu_and_list():
    for args, inp in ((("--pipe",), "q\n"), (("--list",), None)):
        r = menu(*args, inp=inp)
        assert r.returncode == 0, r.stderr
        assert "New checkout: setup.first-time" in r.stdout
        assert "Existing graph node: models.check -> hosts.serve <NODE>" in r.stdout
        assert "Add a model: models.fetch ->" in r.stdout
        assert "NOT DONE YET - FreeBSD llama.cpp 0.7.0 on angel" in r.stdout
        assert "angel is still unmeasured" in r.stdout


def test_piped_choices():
    r = menu("--pipe", inp="2\n2\nb\nq\n")
    assert r.returncode == 0, r.stderr
    assert "Running: python3 scripts/skills.py list" in r.stdout
    assert "green-probe" in r.stdout and "license-blocked" in r.stdout
    # Only invalid picks: menu groups were renumbered, so "9 ... 7" now ran model_db.py backfill
    # (HF network search) and hung until the 120s timeout (#227).
    r = menu("--pipe", inp="99\nx\n2\n99\nb\nq\n")
    assert r.returncode == 0, r.stderr
    assert r.stdout.count("isn't one of the choices") >= 3, r.stdout[-800:]


def test_menu_choice_accepts_environment_assignments_and_forwarded_arguments():
    # Preview twins retired. Exercise NAME=value on a search pick (no license gate).
    r = menu("--pipe", inp="/skills.list\nFAMILIA_TEST_ENV=1 1\nb\nq\n")
    assert r.returncode == 0, r.stderr
    assert "Running: python3 scripts/skills.py list" in r.stdout
    assert "green-probe" in r.stdout


def test_search_choice_accepts_environment_assignments_and_forwarded_arguments():
    # From Set up group, search into Models cards and forward the REPO value.
    r = menu("--pipe", inp="1\n/models.cards\nFAMILIA_TEST_ENV=1 1 org/name\nb\nq\n")
    assert r.returncode == 0, r.stderr
    assert "Running: python3 scripts/hf_fetch.py org/name --damp-run" in r.stdout


def test_long_group_is_paged_instead_of_showing_a_wall_of_items():
    # Hosts has 17 items after preview-twin retirement (page_size 7). Set up is ~7 goals (one page).
    r = menu("--pipe", "--dry-run", inp="8\n>\n<\nb\nq\n")
    assert r.returncode == 0, r.stderr
    assert "Page 1 of 3 (items 1-7 of 17)" in r.stdout
    assert "Page 2 of 3 (items 8-14 of 17)" in r.stdout
    first = r.stdout.split("Page 1 of 3", 1)[1].split("Page 2 of 3", 1)[0]
    assert len(re.findall(r"^  \d+\) ", first, re.M)) == 7
    assert ">) Next page" in first
    assert "<) Previous page" in r.stdout.split("Page 2 of 3", 1)[1]


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


def test_setup_first_time_goal_dry_runs():
    r = menu("--run", "setup.first-time", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("[dry-run]")
    assert "setup_goals.sh first-time" in r.stdout


def test_setup_panel_retired_from_menu():
    keys = {it["key"] for it in items()}
    assert "setup.panel" not in keys
    assert "setup.first-time" in keys and "setup.sync-goal" in keys and "setup.remove-path" in keys
    setup = [it for it in items() if it["group"] == "Set up" and it["cmd"]]
    assert len(setup) <= 8
    assert all("panel.py" not in it["cmd"] for it in items() if it["cmd"])


def test_familia_home_list_goals():
    home = os.path.join(ROOT, "scripts", "familia_home.sh")
    r = subprocess.run(["sh", home, "--list-goals"], cwd=ROOT, capture_output=True, text=True, env=env())
    assert r.returncode == 0, r.stderr
    out = r.stdout
    for goal in ("Talk to the protomodel", "Find more models", "Search my X / Twitter posts",
                 "Install / first-time setup", "Proving grounds", "Legacy menu"):
        assert goal in out, goal
    r2 = subprocess.run(["sh", os.path.join(ROOT, "familia")], cwd=ROOT, capture_output=True, text=True,
                        env=env(FAMILIA_NO_TTY="1"))
    assert r2.returncode == 0, r2.stderr
    assert "Talk to the protomodel" in r2.stdout


def test_familia_legacy_menu_flag():
    r = subprocess.run(["sh", os.path.join(ROOT, "familia"), "--legacy-menu", "--list"],
                       cwd=ROOT, capture_output=True, text=True, env=env())
    assert r.returncode == 0, r.stderr
    assert "setup.first-time" in r.stdout
    assert "test.proving-grounds" in r.stdout


def test_menu_catalog_has_no_baked_dry_run():
    """Items must run for real; dry-run is only the familia-menu.sh --dry-run MODE."""
    banned = ("--dry-run", "-DryRun", "-WhatIf")
    bad = []
    for it in items():
        for col in (it["cmd"], it["win"]):
            toks = col.split()
            for b in banned:
                if b in toks:
                    bad.append(f"{it['key']}: {b} in {col}")
    assert not bad, "baked dry-run still in catalog:\n" + "\n".join(bad)
    keys = {it["key"] for it in items()}
    for twin in ("models.fetch-preview", "hosts.start-preview", "hosts.phone-agent-ask-preview",
                 "setup.sync-preview", "models.add-apply", "setup.install-run", "setup.install-cli-run"):
        assert twin not in keys, twin
    assert "test.proving-grounds" in keys
    assert "test.fleet" not in keys  # folded into test.proving-grounds / proving_grounds.sh


def test_proto_chat_help():
    r = subprocess.run(["sh", os.path.join(ROOT, "scripts", "proto_chat.sh"), "--help"],
                       cwd=ROOT, capture_output=True, text=True, env=env())
    assert r.returncode == 0 and "protomodel" in r.stdout.lower()
