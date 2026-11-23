# Federated fleets, swarms, focus, and transferable runtime state

**Status:** design requirements for [Familia issue #684](https://github.com/brianreborn/familia/issues/684). This document consolidates accepted policy decisions and separates unresolved design choices from current implementation. It does not claim the graph schema, coordinator, or remote KV transfer already implements these requirements.

## Why this is a separate design

Familia's current graph v2 uses `fleets` for green-agentz agent groups and marks `swarms` experimental, with swarms spanning rooms. Those names do not yet encode the enterprise/fleet/swarm identity and trust hierarchy described here. Evolving them requires explicit graph types and validation rather than silently changing the meaning of existing fields. See [configuration-graph.md](configuration-graph.md) and [graph-types.md](graph-types.md).

The goal is one stable orchestration contract that works across hosts, swarms, engines, and optional agent harnesses. A harness may provide a useful implementation of an operation such as fork, but the harness is not required to own multi-host identity, policy, membership, durable task state, or fan-out.

## Organization and identity

### Proposed topology

- An enterprise contains fleets; a fleet groups swarms.
- A host has a stable principal identity independent of hostname, IP address, SSH alias, Unix account, model, or runtime.
- A host can hold explicit membership in multiple fleets and multiple swarms.
- Membership and authorization are separate. Membership alone grants no permission in the parent, child, sibling, or another federated scope.

The organization and execution topology is a DAG, not a tree. Fleets and swarms may have multiple parents; this supports shared placement and classic distributed redundancy across parent paths. Cycles are invalid. Parent edges describe graph relationships, while membership, trust, and authorization remain explicit and independently evaluated. Cross-enterprise access still requires federation grants.

### AAA providers and principals

- Each deployment must support at least one AAA provider; an enterprise may configure multiple providers.
- Familia principals can bind to identities from more than one provider. Explicit administrator-approved binding is the recommended default.
- An enterprise may opt into automatic identity linking using stable issuer/provider plus subject identifiers. Matching names or email addresses alone must not merge identities. Conflicts and ambiguous mappings require review; binding changes are audited and reversible.
- AAA providers authenticate principals and may supply identity or group claims. Familia policy is authoritative for enterprise, fleet, and swarm permissions. Claims grant access only through explicit Familia mappings; required authorization data that is missing or conflicting fails closed.
- How provider attributes are resolved when providers disagree, and whether principal identities are global or enterprise-scoped, remain open.

### Federation

- Cross-enterprise trust is explicit and bilateral. Each enterprise retains its identity and authorization authority.
- The federation grant names accepted external principals and permitted scopes/actions and has expiry and revocation.
- Any authorized bilateral federation permits KV transfer under its existing scope and policy. No extra per-transfer approval is required by default. Deployments may opt into tighter restrictions; revisit the need for finer controls before the 1.0.0 alpha.

## Policy and integrity

### Authorization policy

- Policy inheritance is opt-in per policy and scope; membership and permissions never inherit implicitly. A policy reached through multiple graph paths is deduplicated by its stable identity.
- The most specific applicable child-scope policy wins, even when it overrides an inherited denial.
- At equal specificity across genuinely distinct applicable scopes, explicit deny wins.
- The decision record identifies the effective policy and scope. Provider outages or missing required authorization data fail closed.

### Integrity profiles and flow

Integrity is separate from identity and authorization. Use LOMAC-style low-watermark flow control: consuming lower-integrity input lowers the execution context's effective integrity, restricting subsequent writes to higher-integrity objects.

- Integrity profiles are versioned policy data. Offer multiple sensible presets (including provenance-oriented and traditional low/medium/high profiles) and allow enterprise-defined ordered levels.
- Familia selects and documents one canonical default profile before 1.0.0; the default may change before that release. Do not compare label names or numeric ranks across profiles.
- A task's effective integrity is no higher than its least-integrity input. Preserve integrity and provenance on each fan-out result; a combined result takes the lowest integrity among its contributing results.
- Raising an artifact's integrity requires evidence and an authorized validator distinct from the producing task/principal. Record the validator, policy, evidence, source/result labels, and time. Promotion of an artifact does not relabel its producer or unrelated outputs.
- Federation between different profile versions requires an explicit monotonic mapping approved by both enterprise authorities and pinned to the exact source and destination profile versions. A profile change invalidates the mapping until re-approved.
- Future host-kernel backends may map Familia profiles to LOMAC/MAC labels when the native policy preserves the required ordering and flow rules. Report kernel-native versus application-level enforcement accurately; fail closed for protected operations when native policy and Familia policy diverge.
- Additional security restrictions are opt-in for deployments that need them. Avoid adding default per-operation lockdown controls without a concrete requirement.

## Focus blocks and work coordination

### Focus transaction

A generic focus block scopes a bounded unit of swarm work. It is not a CI/CD mode and does not carry ambient task credentials.

- `/begin focus` opens a block with a unique ID, initiating principal, target scope, expiry, resource budget, explicit environment context, and capability ceiling.
- A hard expiry applies if `/end` is never received. A scheduled recurrence creates a new block rather than leaving an unbounded directive active.
- Child operations are individually identified, authorized, and audited under the parent focus ID. Each receives only a permitted subset of the capability ceiling and credentials just in time. CI/CD credentials are used only by authorized CI/CD child operations.
- Marshal an explicit, portable environment context rather than copying the caller's ambient process environment. Child tasks inherit approved ordinary values and may override task values; they cannot override scope, integrity, deadline, or capability restrictions. Secrets are references and are injected only into the authorized child; never serialize them into focus state or logs.
- `/end` stops accepting and dispatching new children, drains in-flight work, then cancels children still running at the bounded drain deadline. Explicit cancellation may happen sooner.

### Coordinator operations

These are stable orchestration semantics owned by the coordinator and durable ledger, not requirements on an agent harness:

- `/fork` creates one or more child branches under a focus with narrower scope/capability ceilings and inherited approved context.
- A branch may use a harness-native fork or coordinator-managed child workers. Either implementation is valid; use one implementation for each requested branch and preserve the same branch IDs, authorization, lifecycle, and audit semantics.
- `/await` is a barrier over children admitted before its barrier point. It reports per-child terminal results; timeout reports current states without silently cancelling or closing the focus.
- `/join` aggregates terminal outcomes using an explicit rule such as all, quorum, or first-success. It preserves partial failures and integrity labels.
- `/cancel` requests cancellation of a child or subtree and records whether cancellation completed.
- Durable checkpoint/resume is a coordinator-owned recovery mechanism under consideration; delivery phase remains open.

Read-only query fan-out and effectful work (for example CI/CD or repository/issue changes) must be authorized by the capabilities needed for each child operation. Focus and fan-out are generic: they can target registered task classes, capability selectors, or specific queries without broadcasting every request to every member.

### Fan-out behavior

- Select recipients using scope, authorization, verified capabilities, platform/engine support, context requirements, available resources, and task budget.
- Support explicit strategies such as one selected member, selected-N, broadcast, quorum, and first-success/hedged execution.
- A host eligible through multiple selected scopes receives one execution by default. A task may explicitly request per-membership execution.
- Every child has deadline, cancellation, retry/backoff, idempotency information, and an auditable selection/rejection reason. Report partial failure; do not claim exactly-once execution.
- Aggregate only results that contributed. A child failure does not disappear because another child succeeded.

## KV cache and execution-state transfer

Model KV cache is sensitive runtime state containing prompt/context data. It is distinct from focus metadata and ordinary environment values. Fork/join and remote scheduling need an explicit data plane for moving or sharing it.

- Negotiate export/import support by engine. A manifest identifies the model weights/fingerprint, architecture and tokenizer/position configuration, engine/build, context and slot state, KV layout/types, sequence/prefix identity, and integrity profile/label.
- Restore only after all required compatibility checks pass and the transferred bytes verify. Reject mismatches; never silently restore incompatible state.
- Support suitable transports with streaming, flow control/backpressure, resume, quota, cancellation, and source/destination authentication. Cache contents are protected in transit and at rest under the already-authorized federation and local policy.
- Preserve integrity labels during transfer. Any optional lockdown follows deployment policy; no extra per-transfer approval is needed merely because the transfer crosses a valid federation.
- Branches may share a verified prefix snapshot and maintain branch-local suffix state where the runtime supports it. Leases, references, and cleanup must prevent premature deletion and stale/unbounded cache retention.
- When import is unsupported, choose a compatible target, re-prefill only when policy and budget permit, or return an explicit unsupported/incompatible result.
- Report transfer size, duration, compatibility result, restore/cache hit, and failure reason without logging cache contents.

Familia's [C2C stage 1](c2c-stage1.md) is a limited implementation: same model weights, runtime build, context, and KV types with checksum verification. Cross-model projection, broad cross-engine portability, and native remote KV injection remain future capabilities; do not imply they are already supported.

## Implementation sequence

1. Finalize the graph entity/cardinality and principal namespace decisions; add schema types and validation without changing the meaning of existing `fleets`/`swarms` fields silently.
2. Define versioned policy/profile and federation contracts, with focused policy-evaluation and integrity-flow tests.
3. Define focus/child/branch state and coordinator operation API; implement bounded lifecycle, `/await`, fan-out status, and durable event ledger before harness-specific adapters.
4. Add capability-based harness-native/coordinator dispatch adapters, preserving one stable operation contract.
5. Extend KV transport from the existing same-model C2C contract, adding negotiation, transfer, lifecycle, and failure paths before cross-engine projection.
6. Add native kernel-policy integration only on hosts where the backend can enforce the declared profile and report that enforcement truthfully.

## Open decisions before schema/API freeze

- Define multi-parent DAG edge semantics, policy evaluation across multiple paths, and how distributed redundancy uses leases/fencing and failover; also settle principal namespace.
- Define attribute conflict resolution for multiple AAA providers.
- Decide whether focus blocks may be concurrently open, and whether nesting is supported.
- Set the exact `/await` selectors, timeout syntax, and checkpoint/resume release phase.
- Define KV cache retention/lease defaults and when a fresh prefill is permitted.
- Select the canonical integrity profile and review federation/KV lockdown defaults before 1.0.0 alpha.

## Related documentation

- [Configuration graph](configuration-graph.md) and [graph type reference](graph-types.md)
- [Swarm worker requirements](swarm-worker-requirements.md)
- [C2C stage 1](c2c-stage1.md) and [isolated compute](isolated-compute.md)
