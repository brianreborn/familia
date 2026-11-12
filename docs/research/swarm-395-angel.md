# FreeBSD: test_windows Activate.ps1 UTF-8 BOM on host venv

Issue: https://github.com/brianreborn/familia/issues/395
Runner: angel (stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-10 17:18 PST

Status: First pass notes and fix for #395. Section 1 is a read-only
probe run on the runner host. Section 2 documents the approach and solution.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Approach & Verification

### Issue Summary
In FreeBSD test runs, `test_windows.py::test_ps1_files_have_utf8_bom_for_windows_powershell_51`
walked all `.ps1` files under the repository tree via `rglob("*.ps1")` without excluding
untracked virtual environments (such as `.venv/Scripts/Activate.ps1`), which do not have a UTF-8 BOM.
Tracked Windows scripts in the repository do have the required UTF-8 BOM for PowerShell 5.1 compatibility.

### Fix
1. Modified `test_ps1_files_have_utf8_bom_for_windows_powershell_51` to inspect only tracked files via `git ls-files "*.ps1"`.
2. Added `test_untracked_ps1_without_bom_is_ignored` to assert that untracked `.ps1` files in a simulated venv do not trigger test failure.
3. Verified all 8 tests pass cleanly.

## Open Questions

None. Test scoped to tracked `.ps1` files; host venvs safely ignored. Keep #395 open until verified on FreeBSD host.

-- swarm/angel
