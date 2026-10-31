# HVVRAM P1: nvso ABI-3 build + VM test — instructions for an idle LAN machine

— Other Grok Bot ASSIST · executor · 2026-10-31 (PT)

**Status: prepared, NOT run.** Runs only after Brian approves D1 and names the host. HVVRAM yields to pre-release work: if the host is needed for a pre-release, stop and resume later. Nothing here touches angel.

## 0. Preconditions
- Host: any idle LAN machine with VT-x and ≥ 8 GiB free RAM, ≥ 40 GiB free disk. **Probe it live first** (`uname -a`, CPU flags, free RAM/disk) and log the result; no inventory assumptions.
- No root on the host beyond what Brian approves. bhyve needs root; QEMU (user-mode networking, no tap) runs unprivileged on Linux/FreeBSD and is preferred.
- No persistent installs without Brian's OK. Work in `~/hvvram-p1/` only. No curl|sh.
- The ABI-3 fix is **not on GitHub**. It is a local stash (`stash@{0}` = `e2ee54c`, base `aa3339c`) in `/workspace/hvvram/familia` on the assistant box. Export it there with `git stash show -p stash@{0} > nvso-abi3.patch` and copy it to the host over scp; record its sha256.

## 1. Get sources
```
mkdir -p ~/hvvram-p1 && cd ~/hvvram-p1
git clone https://github.com/brianreborn/familia.git && cd familia
git checkout aa3339c && git apply --check ../nvso-abi3.patch && git apply ../nvso-abi3.patch
```

## 2. VM image (FreeBSD 15.1, INVARIANTS + WITNESS)
- Download the official FreeBSD 15.1 amd64 VM image (qcow2) and its CHECKSUM.SHA256 from download.freebsd.org; verify the hash.
- Boot with QEMU: `qemu-system-x86_64 -m 4096 -smp 2 -accel kvm|tcg -drive file=FreeBSD-15.1.qcow2,if=virtio -nic user,hostfwd=tcp::2222-:22 -nographic`
- Inside the VM: install `/usr/src` for 15.1, build a kernel from `GENERIC` + `options INVARIANTS, INVARIANT_SUPPORT, WITNESS, WITNESS_SKIPSPIN` (or use the `GENERIC-DEBUG` config if present), install, reboot. Record `uname -v` and `sysctl kern.conftxt | grep -E 'INVARIANTS|WITNESS'`.

## 3. Build the module in the VM
Copy `gpu-legacy/nvso` into the VM, then `make -f Makefile.kmod` and build `tools/nvsoctl`. Save the full build log.

## 4. Tests (all in the VM)
1. `kldload ./nvso.ko`; check `/dev/nvso0` exists, owner root, mode 0600; `dmesg` shows no WITNESS warnings.
2. `nvsoctl` round-trip on every ioctl; STATS has zeroed padding.
3. Negative tests: unknown flag bits, oversize / undersize `_IOWR`, overflowing lengths, non-power-of-2 depth, overlapping maps, domain-table exhaustion, DESTROY by non-owner → all `EINVAL`/`EPERM`/`ENOSPC`, never success.
4. Races: DESTROY vs DMA_POST from two threads (10k iterations); many-thread ioctls under WITNESS.
5. Unload with an open fd and with an ioctl in flight → refused (`EBUSY`) or drained cleanly, never a panic.
6. Signal death: kill -9 a process holding domains; state released.
7. ABI-2 caller against ABI 3 fails cleanly.
8. 1000× `kldload`/`kldunload` loop.
9. Random-ioctl fuzzer for 4 h (or syzkaller if already available).
10. Reboot test: confirm nothing autoloads (loader.conf/devd/rc).

## 5. Report
- Write `p1-report.md` + logs (build, dmesg, test output, patch sha256, VM image hash, host probe) to **familia-private** under `hvvram/p1/<date>/`, not this public repo. No secrets in logs.
- Post a one-paragraph signed summary on familia #249 only if Brian approved posting.
- Stop. kldload on angel is a separate Brian decision.

## 6. Abort conditions
Any panic not explained by a known defect, any need for root/persistent install not yet approved, or a pre-release needing the host.
