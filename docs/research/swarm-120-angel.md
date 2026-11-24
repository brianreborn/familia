# Hard requirement: align graph vocabulary and schema with Hugging Face metadata

Issue: https://github.com/brianreborn/familia/issues/120
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 16:39 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #120: Hard requirement: align graph vocabulary and schema with Hugging Face metadata

### Hard requirement

Fully locate, document, and adhere to the authoritative Hugging Face Hub metadata formats and conventions that apply to models and tasks. Where Hugging Face already defines a canonical name or concept, familia must use that name rather than inventing a competing node type, role, or field. Keep familia-specific differences to the minimum strictly required to describe coordination concepts that Hugging Face metadata does not represent.

### Scope

- Survey the canonical Hugging Face model-card metadata specification, Hub API metadata, task/pipeline tags, and relevant repository metadata/configuration files; cite authoritative sources and distinguish normative schema from common practice.
- Inventory every familia graph node type, model role, runtime/model field, and generated metadata field; map each to a Hugging Face concept or mark it as a justified familia-only extension.
- Replace redundant or conflicting names with canonical Hugging Face vocabulary where semantics match. Do not force a superficial mapping when the concepts differ.
- Specify the smallest extension vocabulary for coordination-only concepts, explain why each extension is necessary, and define how it round-trips to/from Hugging Face metadata without losing information.
- Update graph schema, validator errors, docs, tests, fixtures, CLI/menu/help, and migration guidance together; preserve existing graphs via an explicit migration or compatibility period.

### Acceptance criteria

- A source-cited mapping table covers the full existing graph vocabulary and identifies gaps.
- Canonical Hugging Face names are used wherever semantics match; every familia-only name has a precise justification.
- The typed schema, generated docs, fixtures, validators, and user-facing examples agree.
- Tests demonstrate metadata import/export round-trips

-- swarm/angel
