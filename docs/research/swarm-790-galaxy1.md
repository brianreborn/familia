# 0.5.0 gateway: graph-owned browser root UI selection

Issue: https://github.com/brianreborn/familia/issues/790
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-27 08:26 PST
Approved-content-sha256: a8805da6f10d29b03f2f2ca1ead10dab89be5aa127bc9911f785d0265419ff04

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18080); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Work note ? Issue #790  
*0.5.0 gateway: graph?owned browser root UI selection*

## (a) What the issue asks

- Implement the **graph declaration** `gateways.<name>.root_ui` for every gateway in Familia.
- Follow the design doc at `docs/design/green-roomz-graph-integration.md`.
- For each `<name>` entry:
  - The value of `.root_ui` must be one of **`unicorn`**, **`llama-ui`**, or **`hermes`**.
  - **Default** to `"unicorn"` when the field is missing or contains an invalid value.
  - **Reject** any unknown value (fail early with a clear error).
- The validated value has to be written into the **Green RoomZ runtime manifest** that is generated for each deployment.
- If a selected UI becomes unavailable at startup, the startup should fail **clearly**, naming the missing UI.
- UI selection must stay out of model?alias URLs; keep `/v1` paths untouched for API endpoints.

---

## (b) Proposed approach & likely files / components

### High?level steps
1. Locate the graph schema and where gateway declarations live (e.g., `graph/gateways/<name>.graph.json` or similar).  
2. Add logic that, when reading a declaration for a gateway:
   - If no value is present ? default to `"unicorn"`.
   - If an explicit value is supplied **and** it matches one of the three known strings (`unicorn`, `llama-ui`, `hermes`) ? use it.
   - Otherwise ? treat as invalid and either fall back to `"unicorn"` after validation or raise a clear error.
3. Pass the validated string into the manifest?generation script that builds the Green RoomZ runtime manifest (e.g., `runtimes/green-roomz-manifest.py`). The field is probably something like `root_ui: "<value>"` in the JSON payload.
4. At startup, run an availability check for each library (`unicorn`, `llama-ui`, `hermes`). If the selected value corresponds to a library that isn?t importable or its root UI component can?t be loaded, raise a clear exception (?Root UI ?<value>? is unavailable ??).
5. Ensure model?alias URLs do **not** embed the `root_ui` field; keep API paths under `/v1`. This may involve tweaking URL generators in `graph/aliases.py` or similar.

### Files / components likely involved
- **Graph schema** ? e.g., `docs/graph/schema.graph` or a per?gateway file such as `gateways/<name>.graph.json`.
- **Gateway node definitions** ? the actual declaration files for each gateway (paths unknown).
- **UI library adapters** ? modules for Unicorn, Llama?UI, Hermes (`ui/unicorn.py`, `ui/llama_ui.py`, `ui/hermes.py`).
- **Manifest generator** ? script that emits the Green RoomZ runtime manifest (e.g., `generate_runtime_manifest.py` or a template).
- **Startup / availability checker** ? code in `startup/check_availability.py` or analogous.
- **URL alias builder** ? logic for model?alias URLs, likely in `graph/aliases.py`.

---

## (c) Risks & test ideas

### Potential risks
- **Defaulting to Unicorn**: Existing configs that expect another UI may break. Need a quick audit of current deployments.
- **Rejecting unknown values**: Must decide whether to error at graph load time or fall back silently; the issue says ?reject?.
- **Private LAN addresses**: Ensure private IP ranges are omitted from commits (e.g., use env vars).
- **Graph validation vs. dry?run mismatch**: Run a full validation before each startup and in CI to catch inconsistencies.

### Suggested tests
1. **Default case** ? No `root_ui` field ? manifest contains `"root_ui":"unicorn"`; startup succeeds if Unicorn is installed.
2. **Valid explicit values** ? Set `root_ui: "llama-ui"` or `"hermes"`. Verify the manifest reflects that value and the corresponding UI module is imported.
3. **Invalid/unknown value** ? Provide `"foo"` ? expect a clear error at graph load time (or startup) naming the rejected value.
4. **Missing capability** ? For a gateway where Unicorn is installed but Llama?UI/Hermes isn?t, set `root_ui: "llama-ui"`. Simulate missing package and confirm startup fails with a message like ?Root UI ?llama-ui? unavailable; falling back to default??.
5. **URL alias check** ? Ensure model?alias URLs do not contain the `root_ui` field.
6. **API paths** ? Verify `/v1` endpoints remain unchanged.

---

## (d) Open questions

- Exact location of `gateways.<name>.root_ui` declarations in the graph schema files.
- The precise key name used in the generated Green RoomZ manifest for storing the root?UI value.
- How ?unavailable? is determined per library (import success, component presence, environment variables?). Need a concrete check or env flag.
- Whether defaulting to Unicorn should apply **only** when no explicit value is given, or also as fallback for missing entries.
- Handling of private LAN addresses: which fields contain them and how to exclude from commits.

-- swarm/galaxy1
