# bt/tracker.py binds a LAN address with no API key

Issue: https://github.com/brianreborn/familia/issues/416
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-23 21:51 PST
Approved-content-sha256: ef39f579e91ccc1ea222ad505038bdd78e4170be6143bb811ccf1c4dafafcf0b

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

(a) The issue is about a security gap where a LAN address is being bound without an API key, which should be rejected according to security policies.

(b) The likely solution involves adding checks for API key presence and ensuring only loopback addresses are allowed, possibly using environment variables or a config file.

(c) Risks include potential unauthorized access if the key is not enforced, and test ideas would focus on simulating LAN bind attempts without a key.

(d) Open questions include how to verify key enforcement and what happens when a key is missing or incorrect.

-- swarm/galaxy1
