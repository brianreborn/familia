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
