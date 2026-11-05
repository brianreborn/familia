# Current sprint — needs attention (updated 2026-11-02)

Single list of everything open across familia, code-bootstraps-llama.cpp (CB), green-roomz, angel-freebsd and familia-private, including work migrated from the other Grok Bot account (Team A → Team B handoffs). Closed/finished items are left out. Merges need 3+ reviews; pushes need Brian's per-push OK.

## 1. Android release — TOP PRIORITY, ship fast
- Target: note9 / Galaxy A57 (Termux). Nothing runs on the phones without Brian's OK.
- CB #13 — Android leftovers after the Galaxy A57 serve (owner: unassigned → next step: live probe, list leftovers, fix).
- green-roomz #38 — merge queue incl. A57 preflight (Team A handoff 5/8).
- familia #277 — ALPHA unattended install on all platforms incl. Android, license gate (spec only; start fresh branch from main).
- familia #203 — Epic: bulletproof small-device deployment.
- familia #275 — ram_safety (Android `sys.platform` handling) awaiting 3rd approval.

## 2. Windows release — do not drop
- sysrescue .55: `\bootmgr` missing on sda1, NTFS flagged unsafe; repair script v3 (Platform Reviewer approved) on hold. Waiting on Brian: v3 OK, WinRE media available?, ddrescue target?, 10:27 QEMU VM origin, unexplained `ntfsfix` run. Drive: 272 reallocated / 49 CRC — check SATA cable. Owner: qodesh Worker.
- install.ps1 on PowerShell 5.1 never executed — CB #14.
- familia PR #273 (pwsh python3/py fallback, #234 partial), #234 (Windows/pwsh tests skipped on Linux), #225 (`&&` in Windows menu command), #32.
- CB #11 (platform pass), CB #32 (Windows parity for start/serve/cockpit/recover).

## 3. Diagrams (separate track)
- Done: familia #284 and CB #84 (architecture diagrams) merged.
- Open: familia #282 — handoff 7/8, `docs/diagrams-2026-10-31` branches had zero commits; close once #284/#84 confirmed to cover it, or list remaining diagrams (green-roomz still has none).

## 4. PRs awaiting review (need 3 approvals)
- familia #275 (RAM safety, 2 approvals in-thread), #276 (bench knobs, blocks miryam LFM3 2-vs-4 thread test), #264 (security H4), #285 (fleet greeting), #274, #268, #251, #250, #240.
- CB #85 (llama.cpp b12032 bump; then update familia pin files), #81 (H3 cockpit auth), #80 (shellcheck), #79 (H2).
- Drafts, do not merge: familia #249 (HVVRAM), #200, #166, #165, #164, #163; familia-private #4. Never merge familia #164/#169, CB #45/#47.

## 5. Push OKs pending from Brian
- familia #248 (Hermes Wiring fix), CB #38 (serve.sh logs API key).

## 6. Closable (fixed on main)
- familia #220, #221, #226.

## 7. Migrated Team A → Team B handoffs (other Grok Bot account)
- familia #277 install ALPHA — spec only, no code.
- familia #278 HF cache resumable downloads — branch `release/llama-bump-hf-cache` @1e13eb9, needs PR + review.
- familia #279 routing queue — 9 branches (`-rebased`), need main merged in + PRs.
- familia #280 merge queue — Boundary/Race/Platform PASS each, merge commits only.
- familia #281 Fuzz nexus_localhost tmp fix `8b34e2a` — needs a disposable host.
- familia #282 diagrams — see §3.
- familia #283 10 lead fix branches from `aa3339c` — merge main, rerun tests, open PRs.
- CB #83 `fix/familia-233-fetch-help` @b522525 — PR + review, then close familia #233.
- CB #82 llama.cpp bump — superseded by CB #85.
- green-roomz #38, #39 (#32/#33 need Brian's confirmation).

## 8. HVVRAM — design only
- angel-freebsd #1–#8 (E0–E6). Nothing runs on angel; ZFS then SSD firmware first. familia #249 draft.

## 9. Other
- Tuning: miryam LFM3 threads test (after #276); gemma on miryam when idle; Qwen3.5-4B on hold.
- CB #22 public transcript — may need history rewrite, Brian decides.
- Test debt: familia #218–#235, #244–#248; security review #236.
- Swap file on sysrescue: lsblk probe, root commands for Brian's approval.

— Other Grok Bot ASSIST
