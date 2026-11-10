"""A57 SSH smoke dispatch: trust, locks, timeouts, and offline phones. SSH is mocked.

No test opens a network connection or talks to a phone. The fake ssh binary records
its argv and environment and exits the way the case asks.
"""
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import time

import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "swarm", "a57_ssh_dispatch.py")
sys.path.insert(0, os.path.join(ROOT, "scripts", "swarm"))
import a57_ssh_dispatch as d  # noqa: E402

ADDR1 = "10.255.255.21"
ADDR2 = "10.255.255.22"
WF = os.path.join(ROOT, ".github", "workflows", "a57-ssh-smoke.yml")
EXAMPLE = os.path.join(ROOT, "docs", "ci", "a57-ssh-ci.yaml.example")


@pytest.fixture
def base():
    parent = os.path.join(ROOT, ".cache")
    os.makedirs(parent, mode=0o700, exist_ok=True)
    path = tempfile.mkdtemp(prefix="test-a57-ssh-", dir=parent)
    os.chmod(path, 0o700)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _write(path, text, mode):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, mode)


def _identity(base):
    path = os.path.join(base, "id_ed25519")
    _write(path, "not-a-real-key\n", 0o600)
    return path


def _known(base, text="pinned-host-key\n"):
    path = os.path.join(base, "known_hosts")
    _write(path, text, 0o644)
    return path


def _inventory(base, devices, known, identity):
    path = os.path.join(base, "inventory.yaml")
    body = {"schema": 1, "devices": {}}
    for name, addr in devices.items():
        body["devices"][name] = {
            "addr": addr,
            "port": 8022,
            "user": "phone",
            "known_hosts": known,
            "identity_file": identity,
        }
    _write(path, yaml.safe_dump(body), 0o600)
    return path


def _mock(base, name, source):
    path = os.path.join(base, name)
    _write(path, "#!/usr/bin/env python3\n" + source, 0o755)
    return path


def _record_mock(record, behavior="ok", sleep=0):
    return textwrap.dedent(f"""\
        import fcntl, json, os, signal, sys, time
        from pathlib import Path
        record = Path({record!r})
        argv = sys.argv
        stdin = sys.stdin.buffer.read()
        addr = ""
        for arg in argv:
            if "@" in arg and not arg.startswith("-"):
                addr = arg.split("@", 1)[1]
        line = json.dumps({{
            "argv": argv,
            "env": dict(os.environ),
            "stdin": stdin.decode(),
            "pid": os.getpid(),
            "addr": addr,
        }})
        with record.open("a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(line + "\\n")
            fcntl.flock(fh, fcntl.LOCK_UN)
        behavior = {behavior!r}
        delay = {sleep!r}
        if behavior == "ignoreterm":
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
        if delay:
            time.sleep(delay)
        if behavior == "offline":
            sys.stderr.write("ssh: connect to host " + addr + " port 8022: Connection refused\\n")
            raise SystemExit(255)
        if behavior == "hostkey":
            sys.stderr.write("Host key verification failed.\\n")
            raise SystemExit(255)
        if behavior == "fail":
            raise SystemExit(12)
        if behavior == "exec":
            fd, name = __import__("tempfile").mkstemp(suffix=".py")
            os.write(fd, stdin)
            os.close(fd)
            os.execv(sys.executable, [sys.executable, "-I", name])
        raise SystemExit(0)
        """)


def _env(base, mock, inventory, **extra):
    home = os.path.join(base, "home")
    locks = os.path.join(base, "locks")
    os.makedirs(home, mode=0o700, exist_ok=True)
    os.makedirs(locks, mode=0o700, exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": home,
        "LANG": "C",
        "A57_SSH_CI_ALLOW_LOCAL": "1",
        "A57_SSH_CI_ALLOW_SSH_OVERRIDE": "1",
        "A57_SSH_CI_SSH": mock,
        "A57_SSH_CI_INVENTORY": inventory,
        "A57_SSH_CI_LOCK_DIR": locks,
        "A57_SSH_CI_BUDGET_SEC": "5",
        "A57_SSH_CI_KILL_GRACE_SEC": "1",
        "A57_SSH_CI_LOCK_WAIT_SEC": "0",
    }
    env.update(extra)
    return env


def _run(args, env, timeout=20):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True,
                          env=env, timeout=timeout)


def _lines(stdout):
    return [ln for ln in stdout.splitlines() if ln]


def _records(path):
    if not os.path.exists(path):
        return []
    rows = []
    for line in open(path, encoding="utf-8"):
        if line.strip():
            rows.append(json.loads(line))
    return rows


def test_help():
    r = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0
    assert "usage" in (r.stdout + r.stderr).lower()


@pytest.mark.parametrize("event,ref,repo,allow,ok,why", [
    ("pull_request", "refs/heads/development", "brianreborn/familia", "1", False, "untrusted-event"),
    ("pull_request_target", "refs/heads/development", "brianreborn/familia", "1", False, "untrusted-event"),
    ("pull_request_review", "refs/heads/development", "brianreborn/familia", "", False, "untrusted-event"),
    ("issue_comment", "refs/heads/development", "brianreborn/familia", "", False, "untrusted-event"),
    ("push", "refs/heads/main", "brianreborn/familia", "", False, "untrusted-ref"),
    ("push", "refs/pull/3/merge", "brianreborn/familia", "", False, "untrusted-ref"),
    ("push", "refs/heads/development", "attacker/familia", "", False, "untrusted-repo"),
    ("workflow_dispatch", "refs/heads/feature", "brianreborn/familia", "", False, "untrusted-ref"),
    ("push", "refs/heads/development", "brianreborn/familia", "", True, "push-development"),
    ("workflow_dispatch", "refs/heads/development", "brianreborn/familia", "", True, "workflow-dispatch"),
    ("", "", "", "", False, "no-event"),
    ("", "", "", "1", True, "local-opt-in"),
])
def test_trust_matrix(event, ref, repo, allow, ok, why):
    env = {"GITHUB_EVENT_NAME": event, "GITHUB_REF": ref, "GITHUB_REPOSITORY": repo}
    if allow:
        env["A57_SSH_CI_ALLOW_LOCAL"] = allow
    else:
        env.pop("A57_SSH_CI_ALLOW_LOCAL", None)
    # Drop empty github keys so a local opt-in is actually eventless.
    if event == "" and ref == "" and repo == "":
        env = {"A57_SSH_CI_ALLOW_LOCAL": allow} if allow else {}
    got_ok, got_why = d.trust_decision(env)
    assert (got_ok, got_why) == (ok, why)


def test_foreign_head_repo_is_refused():
    ok, why = d.trust_decision({
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/development",
        "GITHUB_REPOSITORY": "brianreborn/familia",
        "GITHUB_HEAD_REPOSITORY": "attacker/familia",
    })
    assert (ok, why) == (False, "untrusted-repo")


def test_fork_event_file_is_refused(base):
    event = os.path.join(base, "event.json")
    with open(event, "w", encoding="utf-8") as fh:
        json.dump({"repository": {"fork": True}}, fh)
    ok, why = d.trust_decision({
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_REF": "refs/heads/development",
        "GITHUB_REPOSITORY": "brianreborn/familia",
        "GITHUB_EVENT_PATH": event,
    })
    assert (ok, why) == (False, "untrusted-repo")


def test_untrusted_event_does_not_call_ssh(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    env = _env(base, mock, inv, GITHUB_EVENT_NAME="pull_request_target",
               GITHUB_REF="refs/heads/development", GITHUB_REPOSITORY="brianreborn/familia")
    r = _run(["--devices", "galaxy1"], env)
    assert r.returncode == 2
    assert "reason=untrusted-event" in r.stdout
    assert "status=pass" not in r.stdout
    assert _records(record) == []
    assert ADDR1 not in r.stdout + r.stderr


@pytest.mark.parametrize("devices", [
    "galaxy1;touch /tmp/x",
    "galaxy1\nrm",
    "$(id)",
    "galaxy3",
    "galaxy1 galaxy2",
    "both;galaxy2",
    "",
    "galaxy1,galaxy1",
])
def test_device_injection_refuses_before_ssh(base, devices):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1, "galaxy2": ADDR2}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    r = _run(["--devices", devices], _env(base, mock, inv))
    assert r.returncode == 2
    assert "reason=bad-device" in r.stdout
    assert _records(record) == []


@pytest.mark.parametrize("job", ["python-compile;curl", "bench", "e2e"])
def test_job_allowlist(base, job):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    r = _run(["--job", job, "--devices", "galaxy1"], _env(base, mock, inv))
    assert r.returncode == 2
    assert "reason=bad-job" in r.stdout
    assert _records(record) == []


@pytest.mark.parametrize("sha", ["HEAD", "main", "abc;rm", "$(id)", "xyzxyz1", "../refs"])
def test_bad_sha_refuses(base, sha):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    r = _run(["--devices", "galaxy1", "--sha", sha], _env(base, mock, inv))
    assert r.returncode == 2
    assert "reason=bad-sha" in r.stdout
    assert _records(record) == []


def test_pass_records_ssh_policy_and_hides_addr(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1, "galaxy2": ADDR2}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    sha = "0123456789abcdef"
    r = _run(["--devices", "both", "--sha", sha], _env(base, mock, inv))
    assert r.returncode == 0, r.stderr
    out = _lines(r.stdout)
    assert out[0].startswith("a57-ssh-ci schema=1 job=python-compile trust=local-opt-in sha=" + sha)
    assert out[1:] == ["device=galaxy1 status=pass", "device=galaxy2 status=pass", "overall=pass"]
    assert ADDR1 not in r.stdout + r.stderr
    assert "phone" not in r.stdout
    rows = _records(record)
    assert len(rows) == 2
    for row in rows:
        argv = row["argv"]
        joined = "\n".join(argv)
        assert argv[1:4] == ["-F", "/dev/null", "-T"]
        assert "BatchMode=yes" in joined
        assert "StrictHostKeyChecking=yes" in joined
        assert "StrictHostKeyChecking=no" not in joined
        assert "accept-new" not in joined
        assert "ProxyJump=none" in joined
        assert "ProxyCommand=none" in joined
        assert "ForwardAgent=no" in joined
        assert "IdentitiesOnly=yes" in joined
        assert "IdentityAgent=none" in joined
        assert "ControlMaster=no" in joined
        assert "ControlPath=none" in joined
        assert "ControlPersist" not in joined
        assert "GlobalKnownHostsFile=/dev/null" in joined
        assert f"UserKnownHostsFile={known}" in joined
        assert f"IdentityFile={ident}" in joined
        assert "-A" not in argv
        assert argv[-1] == d.REMOTE_COMMAND
        assert sha not in joined
        assert sha not in row["stdin"]
        assert row["stdin"] == d.REMOTE_SMOKE
        assert set(row["env"]) == {"PATH", "HOME", "LANG", "LC_ALL"}


def test_sha_not_sent_and_rerun_is_idempotent(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    env = _env(base, mock, inv)
    first = _run(["--devices", "galaxy1"], env)
    second = _run(["--devices", "galaxy1"], env)
    assert first.returncode == 0 and second.returncode == 0
    assert _lines(second.stdout)[-1] == "overall=pass"
    assert len(_records(record)) == 2


def test_secrets_are_not_forwarded(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    token = "SENTINEL-TOKEN-VALUE-123456"
    api = "SENTINEL-API-KEY-123456"
    env = _env(base, mock, inv, GITHUB_TOKEN=token, FAMILIA_API_KEY=api, AWS_SECRET_ACCESS_KEY=token)
    r = _run(["--devices", "galaxy1"], env)
    assert r.returncode == 0, r.stdout
    assert token not in r.stdout + r.stderr
    assert api not in r.stdout + r.stderr
    row = _records(record)[0]
    blob = json.dumps(row)
    assert token not in blob and api not in blob
    assert "GITHUB_TOKEN" not in row["env"]
    assert "FAMILIA_API_KEY" not in row["env"]


def test_offline_is_not_pass(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record, behavior="offline"))
    r = _run(["--devices", "galaxy1"], _env(base, mock, inv))
    assert r.returncode == 1
    assert _lines(r.stdout)[-2:] == ["device=galaxy1 status=unavailable", "overall=fail"]
    assert "status=pass" not in r.stdout
    assert ADDR1 not in r.stdout + r.stderr


def test_one_offline_phone_fails_the_run(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1, "galaxy2": ADDR2}, known, ident)
    record = os.path.join(base, "record.jsonl")
    source = _record_mock(record)
    source = source.replace(
        'if behavior == "offline":',
        'if addr.endswith(".22"):\n'
        '    sys.stderr.write("ssh: connect to host " + addr + " port 8022: Connection refused\\n")\n'
        '    raise SystemExit(255)\n'
        'if behavior == "offline":',
    )
    mock = _mock(base, "ssh", source)
    r = _run(["--devices", "both"], _env(base, mock, inv))
    assert r.returncode == 1
    assert "device=galaxy1 status=pass" in r.stdout
    assert "device=galaxy2 status=unavailable" in r.stdout
    assert _lines(r.stdout)[-1] == "overall=fail"
    assert ADDR2 not in r.stdout + r.stderr


def test_hostkey_mismatch_is_one_attempt(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record, behavior="hostkey"))
    r = _run(["--devices", "galaxy1"], _env(base, mock, inv))
    assert r.returncode == 1
    assert "device=galaxy1 status=hostkey" in r.stdout
    assert "status=pass" not in r.stdout
    rows = _records(record)
    assert len(rows) == 1
    assert "StrictHostKeyChecking=yes" in "\n".join(rows[0]["argv"])
    assert "accept-new" not in "\n".join(rows[0]["argv"])


def test_smoke_failure_is_not_pass(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record, behavior="fail"))
    r = _run(["--devices", "galaxy1"], _env(base, mock, inv))
    assert r.returncode == 1
    assert "device=galaxy1 status=fail" in r.stdout


def test_lock_busy_does_not_overlap_and_releases(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record, sleep=1.5))
    env = _env(base, mock, inv, A57_SSH_CI_BUDGET_SEC="8")
    first = subprocess.Popen([sys.executable, SCRIPT, "--devices", "galaxy1"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    deadline = time.time() + 5
    while time.time() < deadline and not os.path.exists(record):
        time.sleep(0.02)
    assert os.path.exists(record), "first dispatch never reached ssh"
    second = _run(["--devices", "galaxy1"], env)
    assert second.returncode == 1
    assert "device=galaxy1 status=busy" in second.stdout
    assert "status=pass" not in second.stdout
    out, err = first.communicate(timeout=10)
    assert first.returncode == 0, err
    assert "device=galaxy1 status=pass" in out
    assert len(_records(record)) == 1
    third = _run(["--devices", "galaxy1"], env)
    assert third.returncode == 0
    assert len(_records(record)) == 2


def test_timeout_kills_process_group_and_releases_lock(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record, behavior="ignoreterm", sleep=30))
    env = _env(base, mock, inv, A57_SSH_CI_BUDGET_SEC="0.4", A57_SSH_CI_KILL_GRACE_SEC="0.3")
    r = _run(["--devices", "galaxy1"], env, timeout=15)
    assert r.returncode == 1
    assert "device=galaxy1 status=timeout" in r.stdout
    assert "status=pass" not in r.stdout
    pid = _records(record)[0]["pid"]
    deadline = time.time() + 2
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError(f"mock ssh pid {pid} still alive")
    fast = _mock(base, "ssh-fast", _record_mock(os.path.join(base, "record-fast.jsonl")))
    env2 = dict(env, A57_SSH_CI_SSH=fast, A57_SSH_CI_BUDGET_SEC="5")
    again = _run(["--devices", "galaxy1"], env2)
    assert again.returncode == 0, again.stdout
    assert "device=galaxy1 status=pass" in again.stdout


def test_phones_run_together(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1, "galaxy2": ADDR2}, known, ident)
    started = os.path.join(base, "started")
    source = textwrap.dedent(f"""\
        import sys, time
        addr = ""
        for arg in sys.argv:
            if "@" in arg and not arg.startswith("-"):
                addr = arg.split("@", 1)[1]
        sys.stdin.buffer.read()
        with open({started!r}, "a") as fh:
            fh.write(addr + "\\n")
        deadline = time.time() + 5
        while time.time() < deadline:
            text = open({started!r}).read()
            if {ADDR1!r} in text and {ADDR2!r} in text:
                raise SystemExit(0)
            time.sleep(0.05)
        raise SystemExit(12)
        """)
    mock = _mock(base, "ssh", source)
    started_at = time.monotonic()
    r = _run(["--devices", "both"], _env(base, mock, inv, A57_SSH_CI_BUDGET_SEC="8"))
    elapsed = time.monotonic() - started_at
    assert r.returncode == 0, r.stdout
    assert elapsed < 3.0, elapsed
    assert _lines(r.stdout)[1:3] == ["device=galaxy1 status=pass", "device=galaxy2 status=pass"]


def test_missing_inventory_is_not_configured(base):
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    missing = os.path.join(base, "no-such.yaml")
    r = _run(["--devices", "both"], _env(base, mock, missing))
    assert r.returncode == 1
    assert "device=galaxy1 status=not-configured" in r.stdout
    assert "device=galaxy2 status=not-configured" in r.stdout
    assert "overall=fail" in r.stdout
    assert "status=pass" not in r.stdout
    assert _records(record) == []


def test_example_inventory_does_not_ssh(base):
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    r = _run(["--devices", "both"], _env(base, mock, EXAMPLE))
    assert r.returncode == 1
    assert "status=not-configured" in r.stdout
    assert "status=pass" not in r.stdout
    assert _records(record) == []


@pytest.mark.parametrize("addr,user,status", [
    ("127.0.0.1", "phone", "refused"),
    ("8.8.8.8", "phone", "refused"),
    ("169.254.1.1", "phone", "refused"),
    ("192.0.2.21", "phone", "not-configured"),
    (ADDR1, "REPLACE_ME", "not-configured"),
    (ADDR1, "phone;rm", "refused"),
    ("galaxy1", "phone", "refused"),
])
def test_bad_targets_do_not_ssh(base, addr, user, status):
    known, ident = _known(base), _identity(base)
    path = os.path.join(base, "inventory.yaml")
    body = {"schema": 1, "devices": {"galaxy1": {
        "addr": addr, "port": 8022, "user": user,
        "known_hosts": known, "identity_file": ident,
    }}}
    _write(path, yaml.safe_dump(body), 0o600)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    r = _run(["--devices", "galaxy1"], _env(base, mock, path))
    assert f"device=galaxy1 status={status}" in r.stdout
    assert "status=pass" not in r.stdout
    assert _records(record) == []
    if status == "refused":
        assert r.returncode == 2
    else:
        assert r.returncode == 1


def test_extra_ssh_option_key_is_refused(base):
    known, ident = _known(base), _identity(base)
    path = os.path.join(base, "inventory.yaml")
    body = {"schema": 1, "devices": {"galaxy1": {
        "addr": ADDR1, "port": 8022, "user": "phone",
        "known_hosts": known, "identity_file": ident,
        "ssh_options": ["-o", "StrictHostKeyChecking=no"],
    }}}
    _write(path, yaml.safe_dump(body), 0o600)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    r = _run(["--devices", "galaxy1"], _env(base, mock, path))
    assert r.returncode == 2
    assert "device=galaxy1 status=refused" in r.stdout
    assert _records(record) == []


def test_loose_file_modes_do_not_ssh(base):
    known, ident = _known(base), _identity(base)
    os.chmod(known, 0o666)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    r = _run(["--devices", "galaxy1"], _env(base, mock, inv))
    assert r.returncode == 2
    assert _records(record) == []
    os.chmod(known, 0o644)
    os.chmod(ident, 0o644)
    r = _run(["--devices", "galaxy1"], _env(base, mock, inv))
    assert r.returncode == 2
    assert _records(record) == []


def test_symlink_identity_is_refused(base):
    known = _known(base)
    real = _identity(base)
    link = os.path.join(base, "link")
    os.symlink(real, link)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, link)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    r = _run(["--devices", "galaxy1"], _env(base, mock, inv))
    assert r.returncode == 2
    assert _records(record) == []


def test_shared_temp_lock_dir_is_refused(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    env = _env(base, mock, inv, A57_SSH_CI_LOCK_DIR="/tmp")
    r = _run(["--devices", "galaxy1"], env)
    assert r.returncode == 2
    assert "reason=bad-lockdir" in r.stdout
    assert _records(record) == []


def test_ssh_override_requires_opt_in(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    env = _env(base, mock, inv)
    del env["A57_SSH_CI_ALLOW_SSH_OVERRIDE"]
    r = _run(["--devices", "galaxy1"], env)
    assert r.returncode == 2
    assert "reason=ssh-override-refused" in r.stdout
    assert _records(record) == []


def test_huge_budget_is_refused(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record))
    r = _run(["--devices", "galaxy1"], _env(base, mock, inv, A57_SSH_CI_BUDGET_SEC="99999"))
    assert r.returncode == 2
    assert "reason=bad-budget" in r.stdout
    assert _records(record) == []


def _prefixed(root):
    try:
        return {n for n in os.listdir(root) if n.startswith("familia-a57-smoke-")}
    except OSError:
        return set()


def test_exec_smoke_over_mocked_ssh_passes_and_cleans(base):
    known, ident = _known(base), _identity(base)
    inv = _inventory(base, {"galaxy1": ADDR1}, known, ident)
    record = os.path.join(base, "record.jsonl")
    mock = _mock(base, "ssh", _record_mock(record, behavior="exec"))
    before = _prefixed("/tmp")
    r = _run(["--devices", "galaxy1"], _env(base, mock, inv))
    assert r.returncode == 0, r.stdout + r.stderr
    assert _prefixed("/tmp") - before == set()
    assert _records(record)[0]["stdin"] == d.REMOTE_SMOKE


def test_remote_smoke_cleans_up_and_second_run_passes(base):
    home = os.path.join(base, "home")
    tmp = os.path.join(base, "tmp")
    os.makedirs(home, mode=0o700)
    os.makedirs(tmp, mode=0o700)
    env = {"HOME": home, "TMPDIR": tmp, "PATH": "/usr/bin:/bin", "LANG": "C"}
    cmd = [sys.executable, "-I", "-c", "import sys; exec(sys.stdin.buffer.read().decode())"]

    def once():
        return subprocess.run(cmd, input=d.REMOTE_SMOKE.encode(), capture_output=True, env=env, timeout=20)

    first = once()
    assert first.returncode == 0, first.stderr
    assert b"compile-ok" in first.stdout
    second = once()
    assert second.returncode == 0, second.stderr
    names = []
    for root, dirs, files in os.walk(tmp):
        names += [n for n in dirs if n.startswith("familia-a57-smoke-")]
    assert names == []


def test_remote_smoke_busy_when_lock_held(base):
    home = os.path.join(base, "home")
    os.makedirs(os.path.join(home, ".cache"), mode=0o700)
    lock_path = os.path.join(home, ".cache", "familia-a57-ci.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    import fcntl
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        env = {"HOME": home, "TMPDIR": base, "PATH": "/usr/bin:/bin", "LANG": "C"}
        r = subprocess.run(
            [sys.executable, "-I", "-c", "import sys; exec(sys.stdin.buffer.read().decode())"],
            input=d.REMOTE_SMOKE.encode(), capture_output=True, env=env, timeout=20,
        )
        assert r.returncode == 11
        assert b"busy" in r.stdout
        assert b"pass" not in r.stdout
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_remote_smoke_source_is_bounded():
    for bad in ("18112", "socket", "pkill", "subprocess", "urlopen", "urllib", "pip",
                "apt", "pkg", "reboot", "termux-wake", "llama", "kill(", "ssh"):
        assert bad not in d.REMOTE_SMOKE
    assert "{" not in d.REMOTE_COMMAND
    argv = d.build_ssh_argv("/usr/bin/ssh", {
        "addr": ADDR1, "user": "phone", "port": 8022,
        "known_hosts": "/srv/known_hosts", "identity_file": "/srv/id",
    })
    assert argv[-1] == d.REMOTE_COMMAND
    assert "18112" not in "\n".join(argv)


def test_scrub_and_secret_render():
    assert d.scrub("connect 10.1.2.3 user u0_a7") == "connect <addr> user <user>"
    leaked = d.render(["device=galaxy1 status=pass SENTINEL-TOKEN-VALUE-123456"],
                      ["SENTINEL-TOKEN-VALUE-123456"])
    assert "SENTINEL" not in leaked
    assert "reason=secret-leak" in leaked


def test_tracked_files_have_no_phone_secrets():
    doc = os.path.join(ROOT, "docs", "ci", "a57-ssh-dispatch.md")
    for path in (SCRIPT, WF, EXAMPLE, doc):
        text = open(path, encoding="utf-8").read()
        assert re.search(r"u0_a\d", text) is None, path
        assert "192.168." not in text, path
        assert ("/home/" + "green") not in text, path
    for path in (SCRIPT, WF, EXAMPLE):
        text = open(path, encoding="utf-8").read()
        assert "StrictHostKeyChecking=no" not in text, path
        assert "accept-new" not in text, path


def test_workflow_shape():
    text = open(WF, encoding="utf-8").read()
    doc = yaml.safe_load(text)
    trigger = doc.get("on", doc.get(True))
    assert "pull_request" not in trigger
    assert "pull_request_target" not in trigger
    assert trigger["push"]["branches"] == ["development"]
    assert "workflow_dispatch" in trigger
    assert doc["permissions"] == {"contents": "read"}
    assert doc["concurrency"]["cancel-in-progress"] is False
    assert doc["concurrency"]["group"] == "a57-ssh-smoke"
    assert "secrets." not in text
    assert "FAMILIA_PRIVATE" not in text
    assert "pull_request:" not in text
    assert "pull_request_target:" not in text
    assert "Android" not in text
    jobs = doc["jobs"]
    assert set(jobs) == {"gate", "smoke", "report"}
    assert jobs["gate"]["runs-on"] == "ubuntu-latest"
    assert jobs["report"]["runs-on"] == "ubuntu-latest"
    assert jobs["smoke"]["runs-on"] == ["self-hosted", "Linux", "swarm-bench", "host:miryam"]
    assert jobs["smoke"]["timeout-minutes"] <= 10
    assert jobs["smoke"]["needs"] == "gate"
    for name, job in jobs.items():
        for step in job.get("steps", []):
            run = step.get("run") or ""
            assert "${{" not in run, name
            if name != "smoke":
                assert "ssh" not in run
                assert "a57_ssh_dispatch" not in run
            if str(step.get("uses", "")).startswith("actions/checkout"):
                assert (step.get("with") or {}).get("persist-credentials") is False
                assert (step.get("with") or {}).get("submodules") is False
    smoke_run = "\n".join(step.get("run", "") for step in jobs["smoke"]["steps"])
    assert "--job python-compile" in smoke_run
    assert "--devices both" in smoke_run
    assert "--inventory" not in smoke_run
    assert "A57_SSH_CI_ALLOW_LOCAL=1" not in text
    assert "A57_SSH_CI_ALLOW_SSH_OVERRIDE=1" not in text
    assert "unset A57_SSH_CI_SSH" in smoke_run
    assert "A57_SSH_CI_INVENTORY" in smoke_run
    assert "A57_SSH_CI_LOCK_DIR" in smoke_run
    assert "ProxyJump" not in smoke_run
