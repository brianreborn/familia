# todo: classify survey models & engines (damp-run results)

Issue: https://github.com/brianreborn/familia/issues/78
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:30 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

Also, clarify what "classify" means here.

We need to classify the models and engines used in the survey results.
The goal is to identify which models were used, their evidence, and their sizes.
We must understand what "classify" means in this context.

We're looking at which models were used in the survey, what evidence we have for each, and what we don't know.
We'll focus on the files that were processed and what they represent.
We should also think about what the next steps should be and where to test.
We don't have exact file contents, so we'll say "unknown" for any that can't be inferred.

We need to understand what "classify" means here.

In short: we need to identify the models, their evidence, and what we don't know. We should outline a plan
to verify and validate these classifications.

We must also consider:
- What files were processed?
- What evidence exists for each model?
- What are the risks if we don't know?
- What tests should we run next?
- How can we validate these classifications?

Now, let's answer each part clearly.

Part (a): What does "classify" mean here?

In this context, "classify" means to identify which models or engines were used based on the evidence from the survey results.
We are looking at the models that were tested (via the repo metadata) and what evidence we have for each.
We are not analyzing the weights or files directly; we are inferring from the repo metadata and the survey's results.
The goal is to understand which models were used and what we know about them.

Part (b): Proposed approach and likely components

We need to:
1. Identify the models that were tested (based on repo metadata).
2. Determine the evidence for each model (e.g., presence of a repo with a specific repo name).
3. Estimate the size of the weights or data used for each model.
4. Consider what we don't know (e.g., exact weights, license info).
5. Think about what tests we should run next (e.g., validate the classification, check for errors).
6. Suggest open questions or next steps.

Part (c): Risks and test ideas

Risks:
- We don't have the exact weights or file contents.
- We don't know if the models were truly used in the survey.
- We might misinterpret the evidence if the repo metadata is incomplete.

Test ideas:
- Check the repo metadata for exact repo names and filenames.
- Compare the repo names with the models listed in the survey.
- Validate the classification by checking if the repo matches the model's purpose.
- Test the models with a small sample to see if they perform as expected.
- Check for license compliance or other issues.

Part (d): Open questions

Open questions:
- What is the exact role of each model in the survey?
- How do we verify the evidence for each model?
- What are the limitations of the current approach?
- Should we focus on a subset of models or expand the search?

Final note: We should not invent file contents or sizes; say "unknown" for any that can't be inferred.

Now, let's write the answer in plain ASCII markdown as requested.
```markdown
# Issue #78:

-- swarm/galaxy1
