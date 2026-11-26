# registry/models: sha256_ok re-stamped without evidence; local username in license path

Issue: https://github.com/brianreborn/familia/issues/619
Runner: box (stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:10 PST
Approved-content-sha256: 1f2b73684c3869baa92ab0d0ff00e6f4c227f8aec852afd78b0164e47ef14383

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18114); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

[a] Issue #619 concerns a regression in `registry/models/dealignai--Nanbeige4.3-33B-UNCENSORED-GGUF--...json`. The file was re-stamped, causing the local `checksum_ok` marker (`local_check.sha256_ok: true`) to be rewritten as a generic "checked [number]" entry and the path, byte count, and audit note removed. The license text path was also rewritten to a user?specific location (`/home/green/.local/share/gguf/hf-meta/....`). This breaks the ability to audit the `sha256_ok` attestation and re?introduces a privacy leak of the local username into shared metadata, violating the #104 rule (no usernames in shared files).

[(b) Proposed approach]

- **Root cause**: `model_db.py` (or the code that writes the registry model) no longer writes relative paths; it now emits absolute paths derived from the host?s home directory (e.g., `/home/green/...`). The `sha256_ok` assertion logic expects either the path and the raw bytes to be kept together, or to drop `sha256_ok` entirely when they are missing.

- **Files / components likely involved**:
  - `registry/models/dealignai--Nanbeige4.3-33B-UNCENSORED-GGUF--...json` ? the model registry entry that was re?dated and rewritten.
  - `model_db.py` ? script that maintains the model database, writes `local_check.sha256_ok`, and constructs paths for the model metadata.
  - The part of the code that computes/asserts `sha256_ok` (the attestation logic) and that rewrites the license text path.
  - Possibly the ?check? script or CI that reads `local_check.sha256_ok`.

- **Suggested fix**:
  1. **Preserve relative paths** when writing the registry entry. Instead of constructing absolute paths from the host, emit paths relative to the repository root (e.g., `~/local/share/gguf/hf-meta/...` or `./local_check.sha256_ok`).
  2. **Keep the path and the raw bytes** whenever `sha256_ok` is asserted. Do not delete the path or the byte?count evidence just because the file was re?stamped.
  3. **Drop `sha256_ok`** only when both the path and the bytes are absent; otherwise keep them.
  4. **Re?run the verification** on the host that actually performed the check, to confirm the new paths and byte hashes match.

[(c) Risks and test ideas]

- **Risks**:
  - *Path resolution*: If relative paths are used, ensure the registry model is read from the same working directory on all machines; otherwise the same file could be interpreted differently.
  - *Integrity verification*: The `sha256_ok` attestation must still be cryptographically verifiable. Keeping the sha256 hash of the file and the path together preserves that.
  - *Privacy*: Avoid embedding the local username (e.g., `/home/green/...`) in shared metadata. The fix should generate paths without the username component or use a generic user directory.
  - *Regression*: Other entries (SmolLM2, Laya) were re?dated similarly; ensure the change is applied consistently across all model registry files.

- **Test ideas (unknown specifics, but high?level)**:
  - After the change, run `model_db.py` on a clean checkout and verify that the generated `local_check.sha256_ok` contains the correct path (relative) and the SHA?256 of the file.
  - Confirm that the license text path no longer points to `/home/green/.local/share/gguf/hf-meta/...` but to a repository?relative location.
  - Perform an audit: pick a known file in the registry, compute its SHA?256, and check that the `sha256_ok` entry matches both the hash and the path.
  - Verify that the `sha256_ok` entry can be removed safely only when the file?s path and bytes

-- swarm/box
