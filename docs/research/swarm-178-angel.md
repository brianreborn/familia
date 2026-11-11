# Installer: download-then-run install-<project> files, plus first-class user, custom and global install scopes

Issue: https://github.com/brianreborn/familia/issues/178
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 16:43 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #178: Installer: download-then-run install-<project> files, plus first-class user, custom and global install scopes

**Done when:** a grep for `| *sh`, `| *bash` and `| *iex` turns up no install instructions in familia or code-bootstraps-llama.cpp.

### Proposed Approach

To address the issue of using pipe-to-shell one-liners in the installer scripts, we propose a two-step pattern: download the installer script to a properly named file, and then run it. This approach ensures that the installation process is more explicit and less prone to errors.

### Files or Components Likely Involved

- **Installer Scripts:** The installer scripts that currently use pipe-to-shell one-liners will need to be updated to follow the two-step pattern.
- **Documentation:** The documentation and READMEs will need to be updated to reflect the new installation process.
- **Code:** The code that handles the installation process will need to be updated to handle the new file-based approach.

### Risks

- **Compatibility:** There is a risk that the new approach may not be compatible with all systems or environments.
- **Security:** There is a risk that the new approach may introduce security vulnerabilities if not implemented correctly.

### Test Ideas

- **Unit Tests:** Write unit tests to ensure that the new installation process works as expected.
- **Integration Tests:** Write integration tests to ensure that the new installation process works with the rest of the system.
- **Security Tests:** Write security tests to ensure that the new installation process does not introduce security vulnerabilities.

### Open Questions

- **User Experience:** Is the new approach easier to use for users?
- **Performance:**

-- swarm/angel
