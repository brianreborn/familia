# Gateway credentials and client selection

**Status:** proposed design. This replaces the accidental single-key behavior
of a gateway with explicit credential lifecycle and client selection.

## Problem

A graph gateway is an API front door. It currently creates one opaque
per-port key and accepts only that key. It has no credential-management
operation and no browser console, so opening the gateway address cannot offer
key selection, creation, rotation, or safe client setup.

The fix is not to put secret management in `graph.yaml` or expose an
unauthenticated HTTP key-management page. A graph owns listeners and routes;
the local Familia operator owns credentials; each client chooses the
credential it presents.

## Terms and ownership

| Term | Owner | Meaning |
| --- | --- | --- |
| gateway | graph | Network listener and API routing contract. |
| credential set | local Familia state | Active and revoked caller credentials for one gateway. |
| credential | local Familia state and one client | One opaque bearer secret with a stable opaque ID and an optional local label. |
| client profile | a client device | Endpoint URL plus the ID of a credential the client already possesses. |
| node key | graph runtime | Internal per-node credential used by the gateway to reach a backend. It is never a caller credential. |

`graph.yaml` may name the gateway but must never contain a credential, a key
file path, a label that identifies a person, or a secret-management policy.
The existing node instance key remains separate from gateway caller keys.

## Requirements

1. **Keyring rather than singleton.** A gateway accepts every active caller
   credential in its credential set. Each has an opaque ID, a persistent
   HMAC fingerprint, state (`active` or `revoked`), creation time, optional
   expiry, and an operator-local label. Secrets are never stored in the
   manifest, logs, graph, generated graph, process arguments, or URL.
2. **One-time disclosure.** Creating a credential produces the secret exactly
   once, only on an explicit operator action. The default output is a
   newly-created mode-0600 file or an interactive secure display. Clipboard
   copy and terminal reveal require an explicit request. Listing a credential
   shows only its ID, label, state, expiry, and fingerprint.
3. **Safe lifecycle.** Create, revoke, and expiry are atomic. Revoke takes
   effect for new requests without a gateway restart. Rotation means create a
   replacement, update clients, then revoke the old credential; there is no
   overwrite-in-place operation.
4. **Client chooses locally.** A client profile selects an imported
   credential by ID. Selecting a profile changes which bearer secret that
   client sends; it never asks the server to reveal or select a secret.
   Profiles are local to the client device, and a browser keeps an entered
   secret in memory by default rather than URL or persistent web storage.
5. **Operator surface is local.** Credential lifecycle is available through
   Familia commands and menu rows on the gateway owner. Remote lifecycle is
   deferred until Familia has an authenticated operator-control plane with
   explicit authorization. The data-plane router remains only a routing API.
6. **Compatible protocols.** The same caller credential applies to every API
   protocol exposed by the gateway. `Authorization: Bearer` and `X-Api-Key`
   remain accepted. Protocol adaptation must not duplicate key stores.
7. **Auditable without disclosure.** Lifecycle events record gateway ID,
   credential ID, fingerprint, event, and timestamp. Events never record the
   secret, an Authorization header, or a client prompt.
8. **Fail closed.** A missing, unreadable, malformed, or inconsistent
   credential set makes the gateway refuse to start. Existing single-key
   instance files migrate as the initial active credential, preserving client
   access until the operator rotates it.

## Storage and runtime contract

For one gateway port, Familia owns a private directory:

```
<config>/familia/instances/<port>/
  credentials.json        # mode 0600: version, generation, metadata only
  credential-secrets/     # mode 0700
    <opaque-id>           # mode 0600: one secret
  credential-events.jsonl # mode 0600: metadata-only lifecycle audit
```

`credentials.json` is atomically replaced and contains only the public
metadata described above. Secrets use one file per credential so revocation
cannot accidentally replace or disclose another secret. The directory is
validated against symlinks and unsafe ownership or modes on every mutation.

The public Green RoomZ gateway reads a complete generation at startup and
reloads a changed, valid generation between requests. It swaps the immutable
in-memory matcher only after all referenced secret files validate. A bad update
leaves the last known-good generation serving and emits a non-secret
health/status error. Startup has no prior generation, so it fails closed.

The old `api-keys` file is migrated once into the first credential. A
compatibility projection containing active secrets may exist only while a
backend requires a multi-line key file; it is generated atomically and is not
the source of truth. Green RoomZ authenticates callers at the public edge; the
internal graph adapter receives the already-authenticated request and uses
separate node credentials for backend calls.

## Familia interface

The command namespace is `familia gateway credential` and maps directly to
menu actions under **Gateways / Access**:

| Operation | Result |
| --- | --- |
| `list --gateway G` | IDs, labels, state, expiry, fingerprints; no secrets. |
| `create --gateway G --label L [--expires AT]` | Creates active credential; writes one mode-0600 handoff file by default. |
| `reveal --gateway G --id ID` | Explicit local confirmation, then displays the secret once. |
| `handoff --gateway G --id ID --output FILE` | Writes a new mode-0600 client handoff file; refuses existing paths. |
| `revoke --gateway G --id ID --reason TEXT` | Atomically disables the credential and records the event. |
| `status --gateway G` | Gateway endpoint, generation, active/revoked counts, and reload health. |
| `client use --endpoint E --credential ID` | Selects an already-imported credential in the local client profile. |

`create` must not print a secret merely because a terminal happened to call
it. The terminal menu offers **Create**, **Copy/reveal**, **Write handoff**,
**Revoke**, and **Select client profile** as distinct actions.

## Green RoomZ browser root and versioned API

The Green RoomZ origin has one browser root at `/`; the Familia graph selects
which UI it serves. `unicorn` is the default, with `llama-ui:<alias>` and
`hermes-webapp` as choices. Hermes Desktop is Electron; its browser renderer is
Hermes Webapp. The root is never a REST endpoint: non-HTML requests receive a
plain 406 pointing clients to `/v1/...`.

- Protocol, inference, model catalog, and other public APIs live under `/v1/`.
  Health and metrics may remain explicit operational endpoints.
- All UIs use the same Green RoomZ origin and caller-auth boundary. The browser
  may enter or change its API key in page memory by default; it is not placed
  in URLs, logs, page source, or persistent browser storage by default.
- The UI selection is graph configuration and must not be duplicated in the
  Green RoomZ host manifest.
- A llama.cpp UI may use engine-specific operations only through explicit
  versioned Green RoomZ routes bound to its graph alias. It must not expose
  unversioned backend REST routes or contact a node directly.
- Every selected UI must keep node credentials server-side and preserve the
  graph catalog, streaming, cancellation, and API-key behavior.

See [`green-roomz-graph-integration.md`](./green-roomz-graph-integration.md)
for the full adapter and acceptance contract.

## Migration and release plan

1. Add the keyring library and its filesystem tests, keeping the current
   `api-keys` value as a migrated active credential.
2. Change Green RoomZ edge authentication to use an immutable active-key
   snapshot and reload valid generations between requests.
3. Add CLI and terminal-menu lifecycle commands, status, and audit records.
4. Integrate the Green RoomZ graph adapter and root UI, then add client profile
   import/selection and the model-specific llama.cpp UI path.
5. Exercise create -> client import -> request -> revoke -> rejected request
   on Linux, FreeBSD, Windows, and Termux through the graph-managed Green
   RoomZ root.

## Acceptance tests

- A fresh graph gateway creates a usable initial credential without exposing
  it in process listings, graph output, or logs.
- Two named credentials authenticate concurrently; revoking one immediately
  rejects it while the other continues to work.
- Restarting preserves the active set and audit metadata.
- A partially written or unsafe credential set is rejected, and a live router
  retains the last known-good set.
- Browser/client selection sends the selected credential and does not persist
  it unless the operator explicitly imports it into that client profile.
- The legacy single-key installation migrates without breaking an existing
  client before the operator rotates it.
