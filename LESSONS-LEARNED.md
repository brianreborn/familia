# LESSONS-LEARNED.md

> **Status note (2026-10-09):** earlier content was a coding agent's private session notes (artifact paths, tool names) and claimed files and regression tests that did not exist. It has been replaced with project lessons.

## L1. Renames leave a long tail (#16)
Renaming feeldznutts → familia left the installer, docs, log prefixes and the logo pointing at the old name. Grep for the old name in code *and* docs, and replace assets in the same change.

## L2. Agent context must match the server slot (#19)
hermes-agent with compression off sent ~18–21k-token requests to a 16,384-token `coder` slot and looped on HTTP 400. Fix: declare both in `graph.yaml`, require `context_length` == per-slot ctx, and launch hermes through `scripts/hermes.sh` with compression on.

## L3. Escaped quotes break shell scripts silently (#14)
A stray `\"` left `android_start.sh` unparseable. Run `sh -n` / shellcheck in CI.

## L4. Never pack a small host's RAM (2026-10-09)
miryam (7 GiB) hard-hung when the 64k coder server, an embed test and a compaction self-test ran together. Keep `reserve_ram_mib: 3072`, ~2 GiB free after estimates, and one heavy process at a time. See `docs/ram-safety.md`.

## L5. SSH passwords
Prefer key auth. If a password is unavoidable, use `sshpass -e` (reads `SSHPASS`), never `-p`, and never disable host-key checking (#18).

## L6. Use ASCII in names and code
Non-breaking hyphens (U+2011) in file names and Python expressions break copy-paste. Keep identifiers ASCII.
