# FreeBSD: test_hermes_upstream_compat KeyError GITHUB_TOKEN

Issue: https://github.com/brianreborn/familia/issues/394
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:38 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

-- FreeBSD: test_hermes_upstream_compat KeyError GITHUB_TOKEN

## Write

(a) What is the issue asking? The issue is about a failing test on the
FreeBSD angel runner. The test is `tests/test_hermes_upstream_compat.py::test_ambient_secrets_not_carried_unless_opted_in`. The test errors with a `KeyError: 'GITHUB_TOKEN'`.

(b) Proposed approach and files: The test indexes `os.environ['GITHUB_TOKEN']` (or an equivalent mapping) instead of using a fixture that sets, and then unsets, a dummy value. On a host without that variable, the test errors before it can assert that ambient secrets are not carried unless opted in. The fix is to drive the test with a controlled dummy value (and a case where the var is absent). Never require a real `GITHUB_TOKEN` or GitHub network access. The assertion should still be: ambient cloud credentials are not passed through unless the documented opt-in is set.

(c) Risks and test ideas: The local CI host does not provide `GITHUB_TOKEN` in the environment (and should not need a real token for this unit test). The risk is that the test might be flaky if the dummy value is not set correctly. Test ideas: Add a test case where the var is absent, and ensure the assertion passes. Also, verify that the test still passes on Linux CI (no regression). No edits to hot-frozen files or FreeBSD/Termux docs. Land the fix on `development`.

(d) Open questions: None known.

-- Other Grok Bot ASSIST

-- swarm/box
