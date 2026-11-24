# ec08176 leftovers beyond #618/#619/#623: fabricated measured: true hosts in generated graphs; stale UNIFIED_ALIAS_DOC.md

Issue: https://github.com/brianreborn/familia/issues/626
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-23 22:21 PST
Approved-content-sha256: a5c9af2fe2a7df822ac7ef53ccd980f2c12e953d6b330bb6b20722a3e0dbc5eb

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

(a) The issue is about ensuring the accuracy and trustworthiness of data used in the family project, specifically around hardware and host information. It highlights concerns about fabricated or misleading data being recorded, which could affect analysis or decisions.

(b) The proposed approach would involve reviewing and updating the relevant files?likely `generated/graph-console.yaml`, `graph-drone.yaml`, `graph-security.yaml`, and `graph-tool-handler.yaml`?to remove or correct the fabricated host entries. The team should also consider adding a warning in the `validate_graph` process when `measured: true` appears in such files. The files related to documentation (`documents/`) should be updated if necessary.

(c) Risks include incorrect modeling of hardware, misallocation of resources, and potential security or compliance issues due to stale or misleading information. Testing should focus on verifying that only real, validated data is used in simulations and analyses.

(d) Open questions include how to identify and correct fabricated data, what criteria should be used to flag such entries, and how to ensure consistent updates across all related files and documentation.

-- swarm/galaxy1
