# Phones out of range: resume phone7 round + llama.cpp version match

Issue: https://github.com/brianreborn/familia/issues/46
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:01 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Status
phone7 / phone8 were out of range for the end of the [number] sprint. Work paused.

## When back on LAN
1. Confirm Wi-Fi on (prior "drops" were radio off ? LESSONS L-wifi).
2. Match **llama.cpp / Termux llama-cpp package versions** across phones before comparing benches (LESSONS L9: 0.5.0 vs 0.6.0).
3. Resume phone7 measurement round (same protocol as phone8 SmolLM2 Vulkan sweep).
4. Identify by host key + boot_id, not DHCP address (LESSONS L12).

Installer / Termux:API notes: #34. Do not put SSH passwords or key material in public issues.

## What the issue asks
The issue asks for the phone7 and phone8 to be measured again after they were out of range during the previous sprint. The goal is to ensure that the measurements are accurate and reliable by comparing the versions of the llama-cpp package across the phones and identifying the phones by their host key and boot_id instead of their DHCP address.

## Proposed approach and files/components likely involved
The proposed approach involves the following steps:
1. Confirm that the Wi-Fi is on on both phones.
2. Match the versions of the llama-cpp package across both phones.
3. Resume the phone7 measurement round using the same protocol as the phone8 SmolLM2 Vulkan sweep.
4. Identify the phones by their host key and boot_id instead of their DHCP address.

The files or components likely involved include:
- The llama-cpp package
- The Termux API
- The phone7 and phone8

## Risks and test

-- swarm/angel
