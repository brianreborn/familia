# Gateway credential lifecycle and client key selection

Issue: https://github.com/brianreborn/familia/issues/786
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-26 10:41 PST
Approved-content-sha256: 30b467c489744af04d940fb8572f14f3d1635c65e758b41e088bd20a4231b210

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18113); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

<think>
</think>**Issue (a): What it asks**

Issue #786 is about the *Gateway* component of the Familia project.  
Currently the graph gateway uses **only one persistent caller key** and lacks any mechanism for managing or selecting client credentials.  
As a result, an API?gateway address (i.e., the URL/endpoint) cannot give the user a proper, context?aware key?selection experience.  
The goal is to introduce a **full credential lifecycle** for the gateway: store multiple per?gateway credentials, manage their metadata and secrets, let the client pick which credential to use, and provide a safe way to create, list, revoke, and audit those credentials.

---

**Issue (b): Proposed approach & likely files/components**

- **Design doc:** `docs/design/gateway-credentials.md` ? to describe the new credential lifecycle (local per?gateway keyring, metadata vs secrets, one?time disclosure, explicit handoff, fingerprint?only listings, atomic revoke, audit trail, client?local selection, local Familia command/menu ops, future Green RoomZ browser console for session?only entry and route discovery, and a migration path from the existing single?key instance file).

- **Keyring / storage:**  
  - A new local keyring (e.g., a JSON/YAML or binary key?store) under each gateway instance that holds **credential entries** and **metadata** (e.g., fingerprint, type, expiry, etc.) in separate files.  
  - Separate files for secrets vs metadata, so the secret can be loaded only when needed.

- **Client?side selection:**  
  - The client (API caller) chooses which credential to present at runtime, rather than the server picking a secret.  
  - This likely involves a small client?side helper that reads the current gateway?s keyring and picks the appropriate entry based on the caller?s context (e.g., fingerprint match, role, or session).

- **Local command/menu operations:**  
  - Extend the existing Familia CLI/menu commands to manage lifecycle tasks: create, list, revoke, audit, etc., all running locally on the gateway process.

- **Browser console (future):**  
  - A Green RoomZ browser console feature for session?only entry and route discovery ? not part of the immediate implementation but noted for later.

- **Migration:**  
  - A migration script or tool that can move the old single?key instance file to the new per?gateway keyring, preserving existing secrets and metadata.

- **Components involved:**  
  - `docs/design/gateway-credentials.md` (design doc)  
  - Existing gateway keyring / instance file (to be replaced)  
  - New keyring storage code (e.g., `gateway/credentials/keyring.json` or similar)  
  - CLI command implementations in the Familia command set (e.g., `gateway credential create`, `list`, `revoke`, `audit`)  
  - Client?side selection logic (likely in the API gateway client library)  
  - Possibly a small browser?console module for future sessions.

---

**Issue (c): Risks & test ideas**

*Risks*

- **Credential confusion:** Storing metadata and secrets separately could lead to mismatched entries if the secret file changes after the metadata is read.  
- **Atomic revoke:** Ensuring revocation of a credential removes it instantly from the client?s view without a race condition.  
- **Client selection without persistent browser storage:** The client must pick a credential each session; if the client caches a credential, it might pick the wrong one.  
- **Cross?platform persistence:** The keyring must survive restarts on Linux, FreeBSD, Windows, and Termux.  
- **Legacy migration:** Converting the old single?key file to the new multi?credential structure without losing data.

*Test ideas (unknown specifics, but high?level)*

- **Concurrent credentials test:** Spawn multiple gateway instances or multiple client sessions that simultaneously create/list credentials and verify no race or duplicate entries.  
- **Immediate revocation test:** Revoke a credential and confirm that subsequent client selections (or API calls) no longer return it.  
- **Persistence across restart test:** Restart the gateway process and verify that previously stored credentials remain available.  
- **Invalid-generation handling:** When a credential?s generation changes (e.g., new secret), ensure old ones are still valid until revoked.  
- **Client selection without persistent browser storage:** Simulate a client picking a credential via an API call; verify the correct secret is used.  
- **Legacy migration test:** Run the migration from the existing single?key instance file to the new keyring and confirm data integrity.  
- **Cross?platform tests:** Run the credential lifecycle commands on Linux, FreeBSD, Windows, and Termux (unknown results ? need to verify).  

---

**Issue (d): Open questions**

- What format should the local keyring use for storing metadata vs secrets? (JSON, YAML, binary?)  
- How will fingerprint?only listings be generated and verified?  
- Where exactly will the ?one-time disclosure, explicit handoff? happen ? is it a UI step or a command line?  
- What is the exact definition of ?client?local credential selection? ? does the client store the chosen credential in a browser console or just pick at runtime?  
- How does the future Green RoomZ browser console integrate with the local keyring?  
- What are the exact command names for the local Familia CLI (e.g., `gateway credential create`, `list`, `revoke`, `audit`)?  
- What are the expected audit?trail fields (who revoked, when, which credential)?  
- How will the migration script handle different existing keyfile layouts on Linux, FreeBSD, Windows, and Termux?  
- What is the expected behavior for ?invalid-generation handling? ? e.g., if a secret is regenerated, should old ones be invalidated?  

*Unknown values:* file contents, exact command implementations, test results, measurement targets.

-- swarm/galaxy1
