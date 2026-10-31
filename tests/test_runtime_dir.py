import fcntl, os, socket, subprocess, sys
import pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import runtime_dir as rd

def test_xdg_private_used(tmp_path):
    x = tmp_path / "xdg"; x.mkdir(mode=0o700)
    assert rd.runtime_dir({"XDG_RUNTIME_DIR": str(x)}) == str(x / "familia")
    assert oct(os.stat(x / "familia").st_mode & 0o777) == "0o700"

def test_symlink_planted_refuses(tmp_path, monkeypatch):
    real = tmp_path / "victim"; real.mkdir(mode=0o700)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    os.symlink(real, tmp_path / ("familia-%d" % os.getuid()))
    with pytest.raises(rd.RuntimeDirError):
        rd.runtime_dir({})

def test_0777_dir_refuses_and_bad_xdg_falls_back(tmp_path, monkeypatch):
    d = tmp_path / ("familia-%d" % os.getuid()); d.mkdir(); os.chmod(d, 0o777)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with pytest.raises(rd.RuntimeDirError):
        rd.runtime_dir({})
    x = tmp_path / "xdg"; x.mkdir(); os.chmod(x, 0o755)  # untrusted XDG
    with pytest.raises(rd.RuntimeDirError):  # falls back to (bad) tmp, still refuses
        rd.runtime_dir({"XDG_RUNTIME_DIR": str(x)})

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
    assert r.returncode != 0 and "refuse" in r.stderr
    os.unlink(tmp_path / ("familia-%d" % os.getuid()))
    r = subprocess.run(["sh", "-c", ". %s; familia_runtime_dir" % sh], capture_output=True, text=True,
                       env={"PATH": os.environ["PATH"], "TMPDIR": str(tmp_path)})
    assert r.returncode == 0 and r.stdout.strip().endswith("familia-%d" % os.getuid())

def test_launch_status_ledger_private(tmp_path, monkeypatch):
    import importlib
    x = tmp_path / "xdg"; x.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(x)); monkeypatch.delenv("FAMILIA_ADMISSION", raising=False)
    import launch_status as ls; ls = importlib.reload(ls)
    assert ls._ledger().startswith(str(x / "familia") + "/")
    ls._locked(lambda led: None)
    assert os.path.exists(ls._ledger())
