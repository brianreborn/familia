# swarm-pull: validate_draft (#580) is never called; model drafts still reach PRs unchecked

Issue: https://github.com/brianreborn/familia/issues/616
Runner: box2 (stamp v=1 host=box2 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-16 22:28 PST
Approved-content-sha256: d11f9e3c2c77bb5501c6857b16786fd3e5957d7de06c3417a2531e4ce869b7b4

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18114); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box2)

stamp v=1 host=box2 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

<think>
</think># Issue #616 ? swarm-pull: validate_draft (#580) is never called; model drafts still reach PRs unchecked

**Context (untrusted body):**  
Commit `83e7562` adds a call to `validate_draft()` inside `scripts/swarm/swarm-pull` (see `:2525` on main `26d9720`). However, the job loop (`job()`) never invokes it. The code path that used to go through `model_draft` ? `draft.md` ? `build_doc` ? `deliver` (lines `:2953`, `:2954-2970`) still exists, and the protection from issue #580 is now dead code.  

The attacker is *remote* to the author?s local text. The author?s text is fenced, but it still feeds a local model whose output ends up in a public PR body. Possible damage: prompt echo, nonce or fence leakage, or truncated output.  

**Fix summary (as proposed in the issue):**  
- Call `validate_draft(draft, nonce)` right after `model_draft` returns, before `draft.md` is written.  
- Initialize the `nonce` on both prompt branches.  
- On `ForgeError`, fail closed: no push, no PR; only the probe?only note is allowed.  
- Match markers case?insensitively.  
- Replace non?ASCII characters in the comments (`:2534-2552`).  
- Add a `job()`?level test asserting that a draft containing the nonce never reaches `deliver()`.

---

## (a) What the issue asks (in my own words)

The issue reports that after commit `83e7562`, the function `validate_draft()` was added to `scripts/swarm/swarm-pull`, but the job loop that should call it (`job()`) never does. As a result, model drafts still flow unchecked into public pull?request bodies. An attacker could craft a remote prompt that leaks a nonce or fence markers, or cause truncated output, and the draft could still be published. The fix is to invoke `validate_draft(draft, nonce)` immediately after the model draft is produced, before the draft is written to `draft.md` and processed further, and to ensure the nonce is initialized on both prompt branches. Additionally, on errors we should fail closed (no push/PR) and add a test to guarantee that a draft containing the nonce never reaches `deliver()`.

---

## (b) Proposed approach & likely files/components

**Proposed change**

1. **Locate the job loop** in `scripts/swarm/swarm-pull` (around line `:2953` ? `model_draft`).  
2. **After `model_draft` returns**, call `validate_draft(draft, nonce)` before any file?write step (e.g., before writing `draft.md`).  
3. **Initialize `nonce`** at the start of each prompt branch (both branches of the conditional).  
4. **On `ForgeError`** (or the corresponding exception), make the job fail closed: skip `deliver()` and push, only emit the probe?only note.  
5. **Case?insensitive marker matching** where markers appear in comments (`:2534-2552`).  
6. **Replace non?ASCII characters** in those comments.  
7. **Add a unit/integration test** at the job level (e.g., in the test suite for `swarm-pull`) that creates a draft containing the nonce and asserts that the resulting `deliver()` call receives a non?empty nonce and that the draft does **not** proceed to `deliver()`.

**Files / components likely involved**

- `scripts/swarm/swarm-pull` ? the script containing `job()`, `model_draft`, and the `ForgeError` handling.  
- The `job()` function definition and its loop.  
- The `validate_draft(draft, nonce)` function (already exists elsewhere, but must be called now).  
- Prompt?generation branches that feed the model (both branches need `nonce

-- swarm/box2
