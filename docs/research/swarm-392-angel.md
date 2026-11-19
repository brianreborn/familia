# FreeBSD: test_bench_idle nice off-by-one (20 == 19)

Issue: https://github.com/brianreborn/familia/issues/392
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:13 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

### Issue Description

The issue involves a FreeBSD test failure in the `test_bench_idle.py` file, specifically the `test_idle_runs_bench_without_force_low_priority_cpu_only` test. The test expects a Linux-style idle niceness of 19, but FreeBSD's nice range allows 20. The stub wrote a nice value of 20 under `.cache/test-bench-idle-.../stub-out/nice`, but the bench itself reported `bench_idle: ok (bench.sh exit 0)`. This indicates an off-by-one in the expected value, not a failed bench run.

### Proposed Approach

To fix this issue, we need to accept the platform idle niceness (19 on Linux, 20 on FreeBSD) or compare against `os.nice` / a documented per-OS maximum, rather than hard-coding 19. This ensures that the test's real goal of the idle bench runs without `--force` and is low priority is met.

### Risks and Test Ideas

- **Risk 1:** Accepting a platform idle niceness might not cover all edge cases or future changes in FreeBSD's nice range.
- **Risk 2:** Hard-coding 19 might lead to regressions on other platforms or future versions of FreeBSD.
- **Test Idea:** Add a test that compares the expected and actual nice values across different platforms to ensure consistency.

### Open Questions

- Should we document the expected niceness values for different platforms in the FreeBSD/Termux docs?
- Are there any other potential issues or edge cases that need to be considered?

-- Other Grok Bot ASSIST

-- swarm/angel
