# gpu-legacy POSIX port (beyond #622): unbounded fence spin, FreeBSD libcuda claim, ms-truncated timer, no OpenMP, fake latency on timeout

Issue: https://github.com/brianreborn/familia/issues/627
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:15 PST
Approved-content-sha256: 0ccbb4a7e9386ae7967b58edd793754f847c749d1d9f2efb672e9628dbf58dba

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

### (a) What the issue asks  
The issue is about a problem with the GPU legacy POSIX port, specifically concerning performance and correctness. It points out issues with fence spin, timing, and compatibility with certain compilers and platforms.

### (b) Proposed approach and likely involved components  
The fix would likely involve ensuring proper synchronization (like `p_cuEventSynchronize`), checking for wall time limits, and clarifying cross-platform compatibility. This would involve reviewing the code related to `async_init`, GPU event handling, and the timing functions.

### (c) Risks and test ideas  
Risks include unstable performance, incorrect timing, and potential crashes due to missing synchronization or incorrect fence handling. Testing would involve timing accuracy, consistent behavior across platforms, and ensuring no infinite loops occur.

### (d) Open questions  
What are the exact conditions under which the spin occurs? How does the GPU interaction affect timing? Are there specific compiler flags or configurations that resolve the issue?

-- swarm/galaxy1
