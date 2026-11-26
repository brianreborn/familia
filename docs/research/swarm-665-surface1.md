# FreeBSD/Angel: verify G84 CUDA 6.5 / NVIDIA 341 runtime and bounded fallback

Issue: https://github.com/brianreborn/familia/issues/665
Runner: surface1 (stamp v=1 host=surface1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-22 22:58 PST
Approved-content-sha256: 7ef7de8ab585ae93519d613d9a3111b75ae2a9030b4087bdb22a36263a0e9b61

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:9931); treat it as unverified until reviewed.

## 1. Read-only probe (measured on surface1)

stamp v=1 host=surface1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

**Issue #665 ? FreeBSD/Angel: verify G84 CUDA 6.5 / NVIDIA 341 runtime and bounded fallback**

---

### (a) What the issue asks

- **Goal:** Determine whether the operator?provided CUDA?6.5 + NVIDIA?341 package set for a FreeBSD?15.1 desktop (Angel) is actually present, free?bsd?compatible, and ready to be installed without touching the host.
- **Scope:**
  1. Locate the operator?supplied CUDA?6.5 / NVIDIA?341 package set (source, platform, checksum, FreeBSD compatibility) **without changing the host**.
  2. Verify if that set is FreeBSD?only, Windows?only, Linux?only, or an archive/source tree.
  3. Confirm provenance and checksums before any install decision.
  4. If the owner later grants a separate live?GPU (G84) authorization, apply a bounded resource guard so inference stays untouched.
  5. Perform a **read?only / build?only probe** first: check module/package/device state, loader search, `libcuda` availability, and G84 PTX support.
  6. Only after the probe succeed should we install packages or start GPU services.

- **Acceptance:** Record verified or unsupported result in `graph.yaml` / docs; never infer capability from PCI identity alone.

---

### (b) Proposed approach & likely files/components

1. **Gather operator?provided artifacts**
   - Look for the CUDA?6.5 and NVIDIA?341 package tarballs/archive on the host.
   - Search FreeBSD package repositories (`pkgconfig`, `pkg`, or a custom archive) for entries matching:
     - Package name(s) like `cuda-6.5` / `nvidia-341` (or similar).
     - Platform field indicating **FreeBSD 15.1** support.
   - Check the operator?s message, email, or CI logs for source URLs, platform tags, and SHA?256 checksums.

2. **Read?only probes**
   - Run `pkg install --dry-run` (or equivalent) to see if the package exists in any repo.
   - Use `modprobe -r` / `lsconfig` style queries:
     ```bash
     ls /dev/nvidia*
     find /usr -name '*cuda*' -o -name '*nvidia*'
     ```
   - Search for `libcuda.so` and `cuInit` symbols via `ldd`, `nm`, or `pkg-config --modpath`.
   - Check PTX availability: try a small kernel compile with `-x cuda=6.5` on the host (read?only) to see if G84 PTX is recognized.
   - Verify device enumeration: `lspci | grep -i g84` and `/dev/dri` presence.

3. **FreeBSD compatibility check**
   - If a package exists, inspect its `PKGINFO`/`PKGBUILD` for FreeBSD?specific build scripts (`bsdbuild`, `pkgconfig` entries).
   - Look for `arch=freebsd` or `target=` fields; if none found, it may be Windows/Linux only.
   - If no package is listed, the source might be an archive (e.g., a tarball with `Makefile.am` and `configure.ac`). Verify that FreeBSD?s build tools can handle it.

4. **Provenance & checksums**
   - Compare any provided SHA?256 hash against the actual file (`sha256sum`).
   - Record source URL, platform tag, and checksum in `graph.yaml`.

5. **Bounded fallback (resource guard)**
   - If we later need to install or load the runtime on Angel:
     - Create a small wrapper script that limits GPU usage while inference runs.
     - Use `cuEventSynchronize` for async fences (as per issue?627 hardening) and keep inference services alive.
     - Only trigger after owner grants separate live?GPU authorization.

6. **Documentation**
   - Update `docs/angel_g84.md` with:
     - What was found / not found,
     - Checksums, source links,
     - PTX support evidence (or ?unknown?),
     - FreeBSD compatibility verdict.

---

### (c) Risks & test ideas

| Risk | Mitigation |
|------|------------|
| **Package missing or wrong version** for FreeBSD 15.1 ? install could pull a Linux?only binary, causing runtime errors on Angel. | Probe with `pkg install --dry-run` and check `PKGINFO` fields before any download. |
| **Live GPU (G84) already loaded but not recognized by the host?s loader** ? fallback needed. | Use `modprobe -r /dev/nvidia*` only after confirming absence; then re?load with correct module path (`nvidia-341-cuda102.x`). |
| **CUDA?6.5 PTX not supported on G84** ? inference may stall or fall back to CPU. | Run a tiny kernel compile: `cat > test.cu <<EOF\n#include <cuda_runtime.h>\nint main(){ cudaMalloc(&d, 256); cudaMemcpy(d,0,1,1); cudaFree(d); }\nEOF && nvcc -x cuda=6.5 -o test.test -I... -L/usr/local/cuda-6.5 -lcudart` (read?only). Look for ?unknown PTX? or link errors. |
| **Inference service must stay running** ? any install that stops it violates scope. | Schedule install after a brief health check; use `systemctl`?like (`service inference status`) to verify before proceeding. |
| **Bounded fallback could starve GPU if not guarded** ? resource contention on Angel. | Implement a simple cgroup/CPU quota or limit number of concurrent kernels during the probe phase. |

---

### (d) Open questions

1. **Exact package names / source tree location** ? Is it a FreeBSD `.pkg` file, an archive tarball, or a Windows?only wheel?  
2. **FreeBSD compatibility evidence** ? Does any existing FreeBSD build script (`configure`, `Makefile`) exist for this CUDA version? If not, is it Linux/Windows only?  
3. **Checksum & provenance** ? What SHA?256 hash was provided by the operator? Where can we retrieve the source (e.g., a GitHub release)?  
4. **NVIDIA runtime modules** ? On Angel, are there any existing `/dev/nvidia*` devices or `nvidia-341` packages installed? The issue says none found yet.  
5. **PTX/compile support for G84** ? Can CUDA?6.5 generate PTX for the GeForce 8600 GT (G84)? This requires checking the vendor driver?s PTX list or a successful `nvcc --ptx` compile on the host.  
6. **Live?GPU authorization** ? Has the operator separately authorized using the G84 GPU as a live accelerator? If yes, we must apply a bounded resource guard before any install/load.

---

*All findings will be recorded in `graph.yaml` and the project docs; no installation or reboot is performed until the owner confirms separate live?GPU authorization.*

-- swarm/surface1
