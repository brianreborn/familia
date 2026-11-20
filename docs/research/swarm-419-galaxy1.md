# Unify the two API key file layouts (api.key vs instances/<port>/api-keys)

Issue: https://github.com/brianreborn/familia/issues/419
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 06:09 PST
Approved-content-sha256: f8dcf9c4000d0301c7000223f7933c1343d9cfcf798e4999a89765027f7070e1

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

I need to understand why two layouts exist and what steps should be taken to resolve them.

The user wants a clear, structured answer in plain text, matching the format.
Please mention the key files and components involved.

RESPONSE: I need to clarify the current inconsistency in the project's key file formats. Two layouts exist: one on disk (`api.key`) and another in the environment (`FAMILIA_API_KEY_FILE`). The goal is to unify them so clients can use either without confusion. The key files involved are `~/.config/familia/api.key` and `~/.config/familia/instances/<port>/api-keys`. The solution should involve migrating the `familia-start` script and related launchers, and ensuring consistent paths are used across all components.

Possible risks include breaking existing scripts and configurations. Testing is needed to confirm that the new layout works with all clients. Open questions involve how to handle edge cases where both paths exist.

What steps should be taken next?

1. Verify the current key file paths and their usage.
2. Migrate the `familia-start` script and related launchers.
3. Update documentation to reflect the new search order.
4. Test the new layout with a subset of clients.
5. Monitor for conflicts or errors.

Any of these steps could help resolve the issue.

What is the expected outcome?

I should focus on the technical steps and risks, not on final results.

----

-- swarm/galaxy1
