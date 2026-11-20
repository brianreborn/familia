import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GPU = ROOT / "gpu-legacy"


def test_async_init_requires_event_synchronize():
    source = (GPU / "sm11_shim.c").read_text()
    guard = "!p_cuEventSynchronize"
    assert guard in source
    async_line = next(line for line in source.splitlines() if "if (!p_cuMemHostAlloc" in line)
    assert guard in async_line


def test_matvec_keeps_double_precision_timer():
    source = (GPU / "bench_matvec.c").read_text()
    assert "#define time_in_ms() sm11_time_ms()" in source
    assert "(long)sm11_time_ms()" not in source
    assert "double t0=time_in_ms();" in source
    assert "double t1=time_in_ms();" in source
    assert "double t2=time_in_ms();" in source
    assert "double t3=time_in_ms();" in source


def test_mapped_probe_reports_incomplete_timeout_as_na():
    source = (GPU / "test_mapped.c").read_text()
    assert "mapped_completed" in source
    assert "event_completed" in source
    assert "n/a (%d/200 complete)" in source


def test_gpu_make_separates_flags_and_supports_openmp_opt_out():
    makefile = (GPU / "Makefile").read_text()
    assert "SM11_CPPFLAGS = -I." in makefile
    assert "OPENMP ?= -fopenmp" in makefile
    assert "$(SM11_CPPFLAGS)" in makefile
    assert "$(OPENMP)" in makefile


def test_nvso_make_preserves_include_with_command_line_cflags():
    makefile = (GPU / "nvso" / "Makefile").read_text()
    assert "NVSO_CPPFLAGS = -Iinclude" in makefile
    assert "$(NVSO_CPPFLAGS)" in makefile
    assert "CFLAGS += -Iinclude" not in makefile


def test_make_dry_runs_keep_include_paths():
    for make in ("make", "bmake"):
        if shutil.which(make) is None:
            continue
        nvso = subprocess.run(
            [make, "-C", str(GPU / "nvso"), "-n", "CFLAGS=-O0", "tools"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        assert "-Iinclude" in nvso.stdout

        legacy = subprocess.run(
            [make, "-C", str(GPU), "-n", "OPENMP=", "CFLAGS=-O0", "all"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )
        assert "-I." in legacy.stdout
