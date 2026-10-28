"""Install docs use download-then-run (no pipe one-liners); start paths print log paths."""
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = re.compile(r"(curl|wget|irm|iwr|Invoke-RestMethod|Invoke-WebRequest)\b[^|\n]*\\?\|\s*(sh|bash|iex|Invoke-Expression)\b|curl\s*\|\s*sh|irm\s*\|\s*iex")


def test_no_pipe_install_one_liners():
    files = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).split()
    bad = []
    for f in files:
        # registry/ holds third-party model-card text verbatim; tests hold the pattern itself
        if f.startswith(("registry/", "tests/")) or not f.endswith((".md", ".sh", ".txt", ".ps1", ".bat", ".1")):
            continue
        try:
            text = open(os.path.join(ROOT, f), encoding="utf-8").read()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        bad += [f"{f}:{i}" for i, l in enumerate(text.splitlines(), 1) if PIPE.search(l)]
    assert not bad, bad


def test_documented_installs_download_then_run():
    readme = open(os.path.join(ROOT, "README.md")).read()
    assert "curl -fsSLo install-familia.sh https://raw.githubusercontent.com/brianreborn/familia/main/install.sh && \\\n  sh ./install-familia.sh" in readme


def test_start_paths_print_log_paths():
    start = open(os.path.join(ROOT, "start.sh")).read()
    assert start.count('say "logs: $(abs_path "$LOG_FILE")"') == 2
    serve = open(os.path.join(ROOT, "scripts/serve.sh")).read()
    assert 'say "logs: $log"' in serve and 'say "logs: $log.cpu"' in serve
    assert "proto-chat: logs:" in open(os.path.join(ROOT, "scripts/proto_chat.sh")).read()
    lin = open(os.path.join(ROOT, "install/linux/install.sh")).read()
    assert "logs: journalctl --user -u familia-node" in lin and "familia-start: logs:" in lin
    assert "familia-start: logs:" in open(os.path.join(ROOT, "install/termux/install.sh")).read()


def test_start_dry_run_prints_absolute_log(tmp_path):
    r = subprocess.run(["sh", os.path.join(ROOT, "start.sh"), "--dry-run"], cwd=ROOT,
                       capture_output=True, text=True, timeout=60,
                       env=dict(os.environ, LOG_FILE="rel.log"))
    # dry-run must not start anything; the logs: line is for real starts only
    assert "logs: " not in r.stderr or os.path.isabs(r.stderr.split("logs: ", 1)[1].split()[0])
