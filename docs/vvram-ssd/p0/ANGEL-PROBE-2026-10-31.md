# angel fingerprint snapshot — 2026-10-31 09:15 PDT

Read-only, non-root probe (user `green`, via miryam's `ssh angel`), approved by Brian 2026-10-31.
A snapshot, not inventory: hardware moves; re-probe before any hardware-dependent step.

| Item | Value |
|---|---|
| hostname | angel |
| FreeBSD | 15.1-RELEASE-p6 (kernel + userland) |
| CPU | Intel Core i5-4570 @ 3.20GHz, 4 CPUs |
| hw.physmem | 25629380608 (~23.9 GiB) |
| GPUs | NVIDIA G84 [GeForce 8600 GT] (vgapci0, pci0:1:0:0); Intel HD 4600 iGPU (vgapci1) |
| SATA | Intel 8 Series/C220 AHCI |
| ada0 | WDC WD10SPCX-24HWST1, 932G, 5400 rpm, serial <redacted> (OS disk) |
| **ada1** | **OCZ-VERTEX2, 149G (160041885696 B), rotationrate 0, serial <VERTEX2-SERIAL in familia-private>, lunid <redacted>** |
| swap | **ada1 is ACTIVE swap** (149G, 347M used); fstab: `/dev/ada1 none swap sw`; old `ada0s1b` swap line commented out |
| ZFS | module not loaded (`zpool`/`zfs` → "Failed to load zfs module", non-root); ARC sysctls not present until loaded |
| camcontrol | not permitted non-root (`/dev/xpt0` Permission denied) |
| fio | not installed → script uses dd fallback |

Notes for P0: swapoff of ada1 must happen with <347M swap in use (fine with ~24 GiB RAM).
Swap would then have no device (ada0s1b is commented out) — Brian to decide whether to re-enable HDD swap (GELI onetime per §5.0).

Signed: Other Grok Bot ASSIST
