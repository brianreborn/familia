# gpu-legacy: Windows LoadLibraryA DLL search order; nvso Makefile lost the CFLAGS override

Issue: https://github.com/brianreborn/familia/issues/622
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:09 PST
Approved-content-sha256: 66ac56d38183b668ee58b1eab8020734993fe74534e008de84fe39643699f301

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

(a) The issue is about a problem with how the build process loads DLLs, specifically related to the order in which Windows loads them and how the Makefile affects the build flags.

(b) We should investigate whether changing the DLL search order or modifying build flags impacts the correct loading of the necessary libraries, especially in relation to the nvso Makefile and the presence of a malicious file in a user-accessible directory.

(c) Risks include potential misloading of critical DLLs, which could cause runtime errors or security issues. Testing should focus on verifying that the correct DLLs are loaded in the expected order and that no malicious files are inadvertently loaded.

(d) Open questions include: What specific changes in the Makefile are causing the issue? How does the nvso build process interact with the search order? Are there any logs or outputs that can help identify the root cause?

-- swarm/galaxy1
