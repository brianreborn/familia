# test: menu item test.offline-secbench uses && in a Windows command; offline_secbench listed as both menu and internal

Issue: https://github.com/brianreborn/familia/issues/225
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 16:47 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #225: test: menu item test.offline-secbench uses && in a Windows command; offline_secbench listed as both menu and internal

**Where:** 
- `tests/test_menu.py::test_item_has_real_command_and_dry_runs[test.offline-secbench]`
- `tests/test_menu.py::test_internal_list_is_current`
- `scripts/menu-items.txt`
- `scripts/menu-internal.txt`

**Error:**
```
AssertionError: Windows commands must not use &&
AssertionError: scripts/offline_secbench.py is in the menu and in menu-internal.txt
```

**Reproduce:** 
- `python3 -m pytest -q tests/test_menu.py -k 'offline-secbench or internal_list'`

**Why it's ignored:** 
- CI (`.github/workflows/lint-warnings.yml` ? `.ci/lint-warnings.sh:54`) only runs `pytest --collect-only`; the suite itself never runs in CI, so this failure is invisible.

**Host needed:** 
- Linux box (verify on miryam)

**Suggested first step:** 
- Rewrite the Windows command for `test.offline-secbench` without `&&` and remove `offline_secbench.py` from `menu-internal.txt`.

---

### Proposed Approach

1. **Rewrite the Windows Command:**
   - Identify the problematic line in `test_menu.py` where the `&&` operator is used in the Windows command for `test.offline-secbench`.
   - Replace the `&&` operator with a semicolon (`;`) to ensure the command works correctly on Windows.

2. **Update `menu-internal.txt

-- swarm/angel
