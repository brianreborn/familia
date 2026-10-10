# LESSONS-LEARNED.md

## Artifact Storage Rules
- All artifact files **must** reside under the session brain directory (`/home/green/.gemini/antigravity-cli/brain/<session-id>/`).
- Regular workspace files (scripts, docs) are created directly in the repository without `ArtifactMetadata`.

## Recent Progress
- Added `android_start.sh` to launch the Android pentest node via SSH.
- Implemented `watchdog_android.sh` to monitor Android protocol hangs.
- Updated `with-fleet.sh` to accept role/manifest arguments.
- Integrated GitHub Issue automation for fleet launches.
- Created regression test skeletons for end‑to‑end verification.

## Pitfalls & Fixes
- **Artifact path errors**: Attempting to write artifacts outside the brain directory caused tool failures. Use plain `write_to_file` for regular files.
- **SSH password handling**: Use `sshpass` and keep the password in an environment variable to avoid interactive prompts.
- **Node ontology bloat**: Represent specialist roles via metadata (`role=pentest`) on generic `task` nodes instead of creating new node types.

## Next Steps (already queued)
- Re‑create a formal `REQUIREMENTS.md` (background task).
- Finalize GitHub Issue hook in `with‑fleet.sh`.
- Run full regression suite and CI integration.

## LittleBit (issue #28, branch feat/littlebit, 2026-10-09)
- **QAT is not optional.** Upstream init alone (Dual-SVID, even with LittleBit-2 ITQ) on stories15M gives PPL 2.6e5–2.7e14 vs dense 1.88 (0% top-1). Per-layer relative output error at eff 1.0: 0.82 SVD-only, 0.68 ITQ. 300 CPU self-distillation steps (~6 min, 4 threads) bring it to PPL 6.31 (eff 1.0) and 6.98 (eff 0.1). Those numbers are a pipeline exercise on same-distribution text, not paper-grade.
- **At small widths the scales dominate.** eff 0.1 on 288-wide layers clamps to rank 8 and stores 0.224 bpw, because the F32 scales outweigh the signs. On K2-Horizon-0.9B-sized layers 0.1 really is ~0.11 bpw.
- **The dense parts decide the size.** After LittleBit, the embedding and an untied head are most of the file (stories15M: 71 of 71.3 MiB; K2-Horizon: 2×188 MiB f16 vs 11.6 MiB of linears). Plan the head's quant and placement first.
- **Keep upstream's bit layout** (int32, LSB first, bit 1 = −1). Conversion is then word copies, and the q/k rope permute only moves whole packed rows plus u1.
- **License:** upstream is CC BY-NC 4.0, so familia imports a user-supplied checkout and vendors nothing.
- **No public sub-1-bit checkpoints** from Samsung. "littlebit-qwen3-4b" GGUFs on HF are ordinary Q4/Q5/Q8.
- `rg PATTERN` with no path in a non-tty shell reads stdin and hangs. Always pass a path.
