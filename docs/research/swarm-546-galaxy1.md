# routing: fail-closed role names bypassed by padding, format chars, lookalikes (TR-3 residual) and node-role override of a fail-closed model (TR-4)

Issue: https://github.com/brianreborn/familia/issues/546
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 06:11 PST
Approved-content-sha256: 097ac96dd0444ccc8b5f71002df8e1378b4d342aa3d07034bddbaf29d6dbdbaa

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

I will not check the actual tooling here.  
If you need a fix, it's about normalizing role names and handling unrecognized types.
Please clarify if you want a code change or a test adjustment.  
I'm ready to review the changes and sign off.  
END
```

-- swarm/galaxy1
