# FreeBSD: Windows reserved names not rejected (COM/LPT superscripts, CONIN$/CONOUT$)

Issue: https://github.com/brianreborn/familia/issues/389
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:08 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue Summary

The FreeBSD project is encountering issues with the `routing_paths.py` test suite, which fails on the `angel` GitHub runner due to the `COM` and `LPT` node names with superscript characters (U+00B9, U+00B2, U+00B3) not being rejected as reserved names. The `CONIN$` and `CONOUT$` console aliases are also not being rejected as reserved names.

## Proposed Approach

1. **Normalize the Path Component**: Modify the `routing_paths.py` test suite to normalize the last path component by case-folding and stripping a trailing extension where Windows would. This will ensure that the `COM` and `LPT` node names with superscript characters are treated as reserved names.

2. **Reject Reserved Names**: Implement logic to reject the `CONIN$`, `CONOUT$`, and `COM` / `LPT` followed by a superscript 1/2/3 (U+00B9, U+00B2, U+00B3) node names.

3. **Keep Existing ASCII Reserved-Name Coverage**: Ensure that the existing ASCII reserved-name coverage is maintained.

4. **Confirm Linux Tests**: Verify that the same tests still pass on Linux CI to ensure no regression.

## Risk and Test Ideas

- **Risk of Breaking Existing Behavior**: There is a risk that this fix might break existing behavior, especially if there are any edge cases or unexpected interactions with other parts of the codebase.
  
- **Testing**: 
  - **Regression Tests**: Run the existing tests on the `angel` GitHub runner to ensure that the fix does not introduce any

-- swarm/angel
