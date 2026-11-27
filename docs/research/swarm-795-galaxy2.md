# 0.5.0 Note9: isolate plain-text versus structured tool calls

Issue: https://github.com/brianreborn/familia/issues/795
Runner: galaxy2 (stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-27 15:33 PST
Approved-content-sha256: e981fbe2dda7eecf99112a411284de4a3f99896088b798f52afff0ab4016c292

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18080); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy2)

stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Issue #795 ? 0.5.0 Note9: isolate plain?text versus structured tool calls

## (a) What the issue asks
On the **Note9 Android release worker** (part of the 0.5.0 / sprint?#683), the model sometimes describes a tool call as raw `json` text instead of emitting a properly structured **`tool_calls`** object through the graph gateway.  
We must:

1. Reproduce and isolate any such case on Note9.  
2. Check the **Familia graph contract**, template/flags, and model?capability metadata before changing code.  
3. Preserve the model?s documented context size.  
4. If the problem is in Familia make a minimal general fix; otherwise write a precise issue comment with evidence and point to the correct upstream owner.

---

## (b) Proposed approach & likely files/components
- **Inspect the current Familia graph** ? look for nodes/edges that represent tool calls.  
- **Llama.cpp?backed tool?call path on Note9** ? trace how model output is turned into a request and then into a `tool_calls` object. This involves:
  - Release?worker code for Note9 (e.g., Android branch, likely under `android-release-worker/...`).  
  - Familia graph handling logic (`familia-graph`, the ?bounded graph?tool? task).  
  - Templates / flags that decide whether to emit a JSON string or a structured object.  
  - Model capability metadata (e.g., files in `models/capabilities/`) that tells the model when it should use tool calls vs plain text.
- **Check contract** ? verify the Graph Gateway API expects a `tool_calls` field; ensure template/flags don?t override it.  
- **Preserve context size** ? keep any documented max?context length unchanged after modifications.

*Suggested (unknown exact) file names / paths*  

| Area | Likely location |
|------|-----------------|
| Familia graph / task definition | `familia/graph/task.py` or similar |
| Llama.cpp tool?call wrapper | `llama.cpp/tool_call_wrapper.py` (Android side) |
| Note9 flags/template config | `note9/flags.yaml` or equivalent |
| Model capability metadata | `models/capabilities/*` |

---

## (c) Risks & test ideas
- **Breaking change risk** ? switching from a plain JSON string to a structured object may break downstream parsers that expect the old shape.  
- **Context?size preservation** ? ensure the model?s context buffer isn?t truncated when emitting tool calls.  
- **Reproducibility on Note9** ? need a device or emulator running the Android release worker; capture logs where plain JSON appears.  

*Test plan (unknown specifics, but high?level)*  

1. Write a script that runs the model with a given prompt and checks whether its output contains `"tool_calls": [...]` **or** just raw `{"key":"value"}`.  
2. Run on known cases (simple tool call, multi?step). Record any failures where plain text is emitted.  
3. After applying a fix: verify every output now includes the proper key; run existing unit tests for graph tasks and llama.cpp integration.

---

## (d) Open questions
- Which **model version / capability flags** on Note9 trigger plain?text tool call output?  
- Is the ?plain text? a stringified JSON object or just an unstructured representation?  
- Which component decides to send `tool_calls` vs raw JSON ? Familia, the llama.cpp wrapper, or the graph gateway?  
- Who owns/owns the Familia graph contract (core Familia team, release?worker maintainers)?  
- How exactly does the model?s documented context size map onto the output format?

---

*Acceptance:* record the exact request shape and structured tool?call result through the graph gateway **or** a reproducible failure with ownership diagnosis. Draft a PR for the code fix (no private LAN addresses or credentials).

-- swarm/galaxy2
