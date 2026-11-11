# Survey (Sep?Oct 2026): Models ? decision (typed-choice) models

Issue: https://github.com/brianreborn/familia/issues/53
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:09 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #53: Survey (Sep?Oct 2026): Models ? decision (typed-choice) models

### (a) What the issue asks

The issue asks for a survey of decision models released since #20, focusing on models suitable for family devices with a 15-year-old target age and a 4.2 GiB model budget. The survey should include models from the HF/GitHub/arXiv APIs, and it should consider the fit of these models based on their size and CPU-friendly nature.

### (b) Proposed approach and the files or components likely involved

1. **Data Collection**: 
   - Collect model names, sizes, and claims from posts in the survey window.
   - Check HF/GitHub/arXiv APIs to identify repositories or papers for each model.
   - Use the public HF/GitHub/arXiv APIs to verify the existence of repositories or papers.

2. **Model Analysis**:
   - Determine the fit of each model based on the family device target age and model budget.
   - Classify models as fitting, maybe fitting, or too big.

3. **File and Component Involvement**:
   - **Markdown Files**: Create a markdown file for the survey, including the list of models, their sizes, claims, and fit classification.
   - **API Calls**: Use Python scripts to make API calls to the HF/GitHub/arXiv APIs.
   - **Data Storage**: Store the collected data in a structured format (e.g., CSV or JSON).

### (c) Risks and test ideas

1. **API Errors**:
   - Risk: API calls may fail or return incorrect data.
   -

-- swarm/angel
