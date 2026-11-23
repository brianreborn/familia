import fcntl, os, socket, subprocess, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import runtime_dir as rd

def test_xdg_private_used(tmp_path):
    x = tmp_path / "xdg"; x.mkdir(mode=0o700)
    assert rd.runtime_dir({"XDG_RUNTIME_DIR": str(x), "TMPDIR": str(tmp_path)}) == str(x / "familia")
    assert oct(os.stat(x / "familia").st_mode & 0o777) == "0o700"

def test_symlink_planted_refuses(tmp_path, monkeypatch):
    real = tmp_path / "victim"; real.mkdir(mode=0o700)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    os.symlink(real, tmp_path / ("familia-%d" % os.getuid()))
    with pytest.raises(rd.RuntimeDirError):
        rd.runtime_dir({"TMPDIR": str(tmp_path)})

def test_0777_dir_refuses_and_bad_xdg_falls_back(tmp_path, monkeypatch):
    d = tmp_path / ("familia-%d" % os.getuid()); d.mkdir(); os.chmod(d, 0o777)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with pytest.raises(rd.RuntimeDirError):
        rd.runtime_dir({"TMPDIR": str(tmp_path)})
    x = tmp_path / "xdg"; x.mkdir(); os.chmod(x, 0o755)  # untrusted XDG
    with pytest.raises(rd.RuntimeDirError):  # falls back to (bad) tmp, still refuses
        rd.runtime_dir({"XDG_RUNTIME_DIR": str(x), "TMPDIR": str(tmp_path)})

def test_foreign_owner_refuses(tmp_path, monkeypatch):
    d = tmp_path / "d"; d.mkdir(mode=0o700)
    monkeypatch.setattr(rd.os, "getuid", lambda: os.stat(d).st_uid + 1)
    with pytest.raises(rd.RuntimeDirError):
        rd.check_private_dir(str(d))

def test_excl_double_create_loses_cleanly(tmp_path):
    p = str(tmp_path / "x.pid")
    os.close(rd.open_excl(p))
    with pytest.raises(FileExistsError):
        rd.open_excl(p)

def test_excl_does_not_follow_symlink(tmp_path):
    tgt = tmp_path / "target"; tgt.write_text("keep")
    os.symlink(tgt, tmp_path / "x.pid")
    with pytest.raises(FileExistsError):
        rd.open_excl(str(tmp_path / "x.pid"))
    assert tgt.read_text() == "keep"

def test_lock_symlink_refused(tmp_path):
    d = tmp_path / "d"; d.mkdir(mode=0o700)
    tgt = tmp_path / "t"; tgt.write_text("keep")
    os.symlink(tgt, d / "a.lock")
    with pytest.raises(OSError):
        rd.open_lock(str(d / "a.lock"))
    assert tgt.read_text() == "keep"

def test_pidfile_live_held_and_stale_takeover(tmp_path):
    d = tmp_path / "d"; d.mkdir(mode=0o700); p = str(d / "s.pid")
    assert rd.acquire_pidfile(p, "serve", pid=111) == (True, "ok")
    ok, why = rd.acquire_pidfile(p, "serve", pid=222, alive=lambda x: True, cmdline=lambda x: "python serve")
    assert not ok and "111" in why
    # alive but recycled pid (cmdline mismatch) -> stale
    assert rd.acquire_pidfile(p, "serve", pid=333, alive=lambda x: True, cmdline=lambda x: "bash")[0]
    assert open(p).read().strip() == "333"
    # dead -> stale
    assert rd.acquire_pidfile(p, "serve", pid=444, alive=lambda x: False)[0]
    assert open(p).read().strip() == "444"

def test_takeover_waits_for_lock(tmp_path):
    d = tmp_path / "d"; d.mkdir(mode=0o700); p = str(d / "s.pid")
    fd = rd.open_lock(p + ".lock"); fcntl.flock(fd, fcntl.LOCK_EX)
    code = ("import sys,fcntl,os;sys.path.insert(0,%r);import runtime_dir as rd;"
            "fd=rd.open_lock(%r);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)") % (rd.__file__.rsplit('/',1)[0], p + ".lock")
    r = subprocess.run([sys.executable, "-c", code], capture_output=True)
    assert r.returncode != 0  # second taker cannot take the lock while held
    os.close(fd)

def test_socket_unlink_only_ours(tmp_path):
    d = tmp_path / "d"; d.mkdir(mode=0o700)
    s = socket.socket(socket.AF_UNIX); s.bind(str(d / "a.sock")); s.close()
    assert rd.safe_unlink_socket(str(d / "a.sock")) and not (d / "a.sock").exists()
    (d / "f.sock").write_text("x")
    assert rd.safe_unlink_socket(str(d / "f.sock")) is False and (d / "f.sock").exists()

def test_sh_helper_refuses_symlink(tmp_path):
    real = tmp_path / "v"; real.mkdir(mode=0o700)
    os.symlink(real, tmp_path / ("familia-%d" % os.getuid()))
    sh = os.path.join(os.path.dirname(rd.__file__), "runtime_dir.sh")
    r = subprocess.run(["sh", "-c", ". %s; familia_runtime_dir" % sh], capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "TMPDIR": str(tmp_path)})
    assert r.returncode != 0 and "reject" in r.stderr
    os.unlink(tmp_path / ("familia-%d" % os.getuid()))
    r = subprocess.run(["sh", "-c", ". %s; familia_runtime_dir" % sh], capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "TMPDIR": str(tmp_path)})
    assert r.returncode == 0 and r.stdout.strip().endswith("familia-%d" % os.getuid())

def test_cache_dir_preferred_over_tmp(tmp_path, monkeypatch):
    home = tmp_path / "home"; home.mkdir(mode=0o700)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    got = rd.runtime_dir({"HOME": str(home)})
    assert got == str(home / ".cache" / "familia" / "run")
    assert oct(os.stat(got).st_mode & 0o777) == "0o700"
    assert not (tmp_path / ("familia-%d" % os.getuid())).exists()
    xc = tmp_path / "xc"; xc.mkdir(mode=0o700)
    assert rd.runtime_dir({"XDG_CACHE_HOME": str(xc), "HOME": str(home)}) == str(xc / "familia" / "run")

def test_bad_cache_falls_to_tmp_with_logged_reason(tmp_path, monkeypatch, caplog):
    home = tmp_path / "home"; (home / ".cache" / "familia").mkdir(parents=True)
    (home / ".cache" / "familia" / "run").mkdir(); os.chmod(home / ".cache" / "familia" / "run", 0o755)
    t = tmp_path / "t"; t.mkdir(); monkeypatch.setenv("TMPDIR", str(t))
    with caplog.at_level("WARNING", logger="familia.runtime_dir"):
        got = rd.runtime_dir({"HOME": str(home), "TMPDIR": str(t)})
    assert got == str(t / ("familia-%d" % os.getuid()))
    assert "reject cache candidate" in caplog.text and "group/other" in caplog.text

def test_precreated_foreign_tmp_fallback_rejected_logged(tmp_path, monkeypatch, caplog):
    d = tmp_path / ("familia-%d" % os.getuid()); d.mkdir(mode=0o700)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    real = os.stat(d).st_uid
    monkeypatch.setattr(rd.os, "getuid", lambda: real + 1)  # d now looks foreign-owned
    d2 = tmp_path / ("familia-%d" % (real + 1)); d2.mkdir(mode=0o700)  # attacker pre-created
    with caplog.at_level("WARNING", logger="familia.runtime_dir"):
        with pytest.raises(rd.RuntimeDirError):
            rd.runtime_dir({})
    assert "reject tmp candidate" in caplog.text and "foreign owner" in caplog.text

def test_sh_cache_preferred_and_reason_logged(tmp_path):
    home = tmp_path / "home"; home.mkdir(mode=0o700)
    sh = os.path.join(os.path.dirname(rd.__file__), "runtime_dir.sh")
    env = {"PATH": os.environ["PATH"], "TMPDIR": str(tmp_path), "HOME": str(home)}
    r = subprocess.run(["sh", "-c", ". %s; familia_runtime_dir" % sh], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout.strip() == str(home / ".cache/familia/run")
    os.chmod(home / ".cache/familia/run", 0o755)
    r = subprocess.run(["sh", "-c", ". %s; familia_runtime_dir" % sh], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and r.stdout.strip().endswith("familia-%d" % os.getuid())
    assert "reject" in r.stderr and "group/other" in r.stderr

def _load_ls(monkeypatch, ledger):
    import importlib
    monkeypatch.setenv("FAMILIA_ADMISSION", ledger)
    import launch_status as ls
    return importlib.reload(ls)

def test_launch_status_locked_uses_open_lock(tmp_path, monkeypatch):
    d = tmp_path / "d"; d.mkdir(mode=0o700)
    ls = _load_ls(monkeypatch, str(d / "led.json"))
    ls._locked(lambda led: None)
    assert (d / "led.json").exists()

def test_launch_status_locked_rejects_symlink_lock(tmp_path, monkeypatch):
    d = tmp_path / "d"; d.mkdir(mode=0o700)
    tgt = tmp_path / "victim"; tgt.write_text("keep")
    os.symlink(tgt, d / "led.json.lock")
    ls = _load_ls(monkeypatch, str(d / "led.json"))
    with pytest.raises(OSError):
        ls._locked(lambda led: None)
    assert tgt.read_text() == "keep" and not (d / "led.json").exists()

def test_launch_status_default_ledger_private(tmp_path, monkeypatch):
    import importlib
    x = tmp_path / "xdg"; x.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(x)); monkeypatch.delenv("FAMILIA_ADMISSION", raising=False)
    import launch_status as ls; ls = importlib.reload(ls)
    assert ls.LEDGER.startswith(str(x / "familia") + "/")

def test_tmp_base_honors_passed_env(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", "/should/not/be/used")
    assert rd._tmp_base({"TMPDIR": str(tmp_path)}) == str(tmp_path)
    assert rd._tmp_base({}).endswith("/tmp")
