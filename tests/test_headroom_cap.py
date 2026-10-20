import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import bench_guard as b

def test_headroom_cap():
    f = tempfile.NamedTemporaryFile("w", delete=False); f.write("MemTotal: 24000000 kB\nMemAvailable: 12582912 kB\n"); f.close()
    assert b.headroom_cap_mib(1536, f.name) == 12288 - 1536

def test_threads_in_use():
    ps = "/x/llama-server -m a -t 4\n/x/llama-bench -m b -t 2,4\npython3 foo -t 9\n"
    assert b.threads_in_use(ps) == 8
