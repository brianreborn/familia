# Hardware inventory (canonical)

**This file is the single source of truth for where hardware physically is.** Any doc that says which host has which CPU, GPU, IOMMU, or disk must link here. It must not restate facts that conflict with this file. `scripts/check_hw_claims.py` enforces the link. Update this file **first** when hardware moves or a host is reinstalled, and date the change.

Each row says how we know: **Brian** (owner statement), **measured** (command output with a date), or **historical** (true once, may be stale).

| Host | OS | CPU | IOMMU | GPU | RAM | Storage | Source / date |
|---|---|---|---|---|---|---|---|
| **angel** (aka Uriel), 192.168.4.25 | FreeBSD 15.1 | Intel i5-4570 (Haswell, 4C/4T) | VT-d capable CPU; **chipset DMAR table unverified** | **GeForce 8600 GT (G84, 256 MiB), installed in angel** | 24 GiB | OS disk; HDD (swap); OCZ Vertex 2 (spare, HVVRAM tier/FW target) | Brian 2026-10-27 (Vertex 2, swap) and **2026-10-31 (G84 is in angel)**; CPU/RAM from familia-private 3fbb1c2 |
| qodesh | Windows 10 | AMD Athlon II X2 (x86-64-v1, no AVX) | none usable | GeForce 8600 GT (G84) on 341.92 | 16 GiB | — | measured 2026-10 (`registry/hardware/nvidia-g84-8600gt-athlon2x2-win10.yaml`) |
| miryam | Linux | Intel i5-7200U | — | Intel HD 620 (Vulkan) | — | — | `registry/hardware/intel-kbl-i5-7200u-hd620-linux.yaml` |
| centos10-bigram | CentOS Stream 10 | i5-4570 | — | 8600 GT (340.108, unbound) | 23 GiB | — | **historical** 2026-10-19. Matches angel's CPU/RAM/GPU; whether angel is this chassis reinstalled with FreeBSD is **unconfirmed (ask Brian)** |
| (FreeBSD Athlon II + 8600 GT, angel-freebsd `cuda-8600gt` NOTES) | FreeBSD 15.1 | Athlon II X2 B24 | — | 8600 GT | — | — | **historical** 2026-09-26. Which host this was is **unconfirmed**. Do not cite it as angel's current hardware |

Rules:
- Never infer hardware location from a project's notes, an old benchmark, or an X post. Cite this file.
- A "historical" row is never evidence of current state.
- A change of OS on a chassis (CentOS → FreeBSD) or a moved card is a new dated row plus an update here, in the same PR.
