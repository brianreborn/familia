# Epic: bulletproof small-device deployment

Issue: https://github.com/brianreborn/familia/issues/203
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:41 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

And I'll keep it short.

**Short Answer**

This is about making the installer and deployment process rock-solid for tiny devices?so it works, even when things go wrong. We need a one-click install, stable local builds, and fast recovery from network hiccups. We should test on many platforms, and keep the build process fully functional if it fails.

What components should we focus on? (Installer, build server, test scripts, etc.)  
What risks stand in the way? (Network, tooling, edge cases)  
What tests should we run? (Automated, manual, CI)  
What questions still need answering? (Performance, edge cases, tooling)

-- swarm/galaxy1
