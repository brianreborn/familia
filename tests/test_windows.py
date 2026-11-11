import copy, os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from graph_types import validate_types  # noqa: E402
import validate_graph  # noqa: E402
BASE = validate_graph.load(os.path.join(ROOT, "graph.yaml"))
def w(): x = copy.deepcopy(BASE); return x, x["hosts"]["qodesh"]["windows"]
def has(x, frag):
    e = validate_types(x); assert any(frag in m for m in e), e

def test_qodesh_windows_block():
    win = BASE["hosts"]["qodesh"]["windows"]
    assert win["autostart"] is False and win["avx_required"] is False
    assert os.path.exists(os.path.join(ROOT, *win["start_script"].split("\\")))

def test_windows_checks():
    x, v = w(); v["autostart"] = True; has(x, "autostart true needs startup scheduled-task")
    x, v = w(); v["startup"] = "scheduled-task"; del v["task_name"]; has(x, "needs task_name")
    x, v = w(); del v["start_script"]; has(x, "needs start_script")
    x, v = w(); v["avx_required"] = "no"; has(x, "expected true/false")
    x, v = w(); v["startup"] = "scheduled-task"; v["autostart"] = True; assert validate_types(x) == []

def test_scripts_shape():
    bat = open(os.path.join(ROOT, "scripts/windows/start.bat"), newline="").read()
    assert "E:\\temp\\familia\\models" in bat and "%USERPROFILE%\\familia\\models" in bat
    assert "127.0.0.1" in bat and "AVX" in bat
    assert "--api-key-file" in bat and "bind_auth_guard.py" in bat
    assert "--extra-start" in bat and '"%FAMILIA_EXTRA%"' in bat
    assert "set \"LLAMA_API_KEY=\"" in bat
    assert "for %%T in (%FAMILIA_EXTRA%)" not in bat
    ps = open(os.path.join(ROOT, "scripts/windows/install-task.ps1")).read()
    assert "SupportsShouldProcess" in ps and "-AtLogOn" in ps and "RunLevel Limited" in ps
    # opt-in: without -Install the script returns before registering
    assert ps.index("if (-not $Install)") < ps.index("Register-ScheduledTask")


def test_ps1_files_have_utf8_bom_for_windows_powershell_51():
    """#234: Windows PowerShell 5.1 reads BOM-less .ps1 as ANSI (cp1252). UTF-8 glyphs such as
    '║' (E2 95 91) then contain 0x91/0x92, which 5.1 treats as quote characters, so
    familia-home.ps1 / setup-goals.ps1 failed to parse. Every .ps1 must start with a UTF-8 BOM."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    bad = [str(p.relative_to(root)) for p in root.rglob("*.ps1")
           if ".git" not in p.parts and not p.read_bytes().startswith(b"\xef\xbb\xbf")]
    assert not bad, f"add a UTF-8 BOM (PowerShell 5.1 parses these as ANSI): {bad}"


def test_start_bat_echo_parens_in_blocks_are_escaped():
    """Unescaped ) in an echo inside a ( block closes the block; exit then runs always."""
    bat = open(os.path.join(ROOT, "scripts/windows/start.bat"), newline="").read()
    assert "\r\n" in bat and "\n" not in bat.replace("\r\n", "")
    depth = 0
    bad = []
    for i, raw in enumerate(bat.split("\n"), 1):
        line = raw.rstrip("\r")
        stripped = line.strip()
        if stripped.lower().startswith("rem "):
            continue
        if depth > 0 and stripped.lower().startswith("echo ") or (
            depth > 0 and stripped.lower().startswith("echo\t")
        ):
            payload = stripped[4:]
            j = 0
            while j < len(payload):
                if payload[j] == "^" and j + 1 < len(payload) and payload[j + 1] in "()":
                    j += 2
                    continue
                if payload[j] in "()":
                    bad.append("%s:%d: unescaped %r in echo inside a block: %s" % (
                        "scripts/windows/start.bat", i, payload[j], stripped))
                    break
                j += 1
            # do not let echo text change depth
            continue
        # count unescaped, unquoted parens for block depth
        in_q = False
        j = 0
        while j < len(stripped):
            c = stripped[j]
            if c == "^" and j + 1 < len(stripped):
                j += 2
                continue
            if c == '"':
                in_q = not in_q
                j += 1
                continue
            if in_q:
                j += 1
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            j += 1
    assert not bad, bad
    assert depth == 0


def test_start_bat_hands_extra_to_the_guard():
    """Boundary: FAMILIA_EXTRA override check lives in the guard, not a cmd for-loop."""
    import bind_auth_guard as g
    bat = open(os.path.join(ROOT, "scripts/windows/start.bat"), newline="").read()
    assert "--extra-start \"%FAMILIA_EXTRA%\"" in bat
    # the three refusals Boundary asked to test include start.bat EXTRA tokens
    ok, msg = g.check([
        "llama-server.exe", "--host", "127.0.0.1", "--port", "9941",
        "--api-key-file", "C:\\unused", "--extra-start", "--host=0.0.0.0",
    ])
    assert ok is False and "extra-start" in msg and "--host" in msg
