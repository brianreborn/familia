# Admin review queue

Generated at: **2026-11-10 00:33 UTC**

Snapshot for Brian (repository administrator) of every open familia issue, and every open pull request, that is waiting on his personal review or decision. GitHub author on all of these is `brianreborn`, because swarm agents post through that account. Where a comment is signed, the signing agent is named below.

## Criteria

Included when the next action is a decision, confirmation, or approval from the administrator:

- Labels were checked on every open issue. None of the open issues use `needs-review`, `admin`, `needs-decision`, `awaiting-owner`, `question`, or `blocked`. The `question` label exists and is unused. `deferred` on [#38](https://github.com/brianreborn/familia/issues/38) records a decision already made (EmbeddingGemma stays off). No open issue or pull request has an assignee.
- The issue body or a comment asks Brian, the owner, or the admin to decide, confirm, or approve, and that ask is still the outstanding gate.
- The item is explicitly next up: label `priority:top`, or a checklist headed "Decisions awaiting user".
- An open pull request is included only when its body or comments hold the merge, or a product choice, for Brian ("Do not merge without Brian exact yes", "holding for Brian", "pending Brian's choice", "nothing gets built until Brian approves each phase").

Left off this page (136 open issues and 8 open pull requests):

- Implementation, test, survey, and `rt-idea` work whose next step is an agent, a galaxy review queue ([#325](https://github.com/brianreborn/familia/issues/325), [#326](https://github.com/brianreborn/familia/issues/326)), or a box-only experiment. A standing line such as "no fleet install without Brian's OK" did not by itself count.
- Decisions already recorded ([#38](https://github.com/brianreborn/familia/issues/38), [#77](https://github.com/brianreborn/familia/issues/77) deferred 2026-10-19, galaxy sign-offs on [#319](https://github.com/brianreborn/familia/issues/319), [#320](https://github.com/brianreborn/familia/issues/320), [#322](https://github.com/brianreborn/familia/issues/322), [#323](https://github.com/brianreborn/familia/issues/323), and the "Approve" comment on [#327](https://github.com/brianreborn/familia/issues/327)).
- Claims that mention a future per-push OK but do not have a finished patch waiting ([#32](https://github.com/brianreborn/familia/issues/32), [#218](https://github.com/brianreborn/familia/issues/218), [#225](https://github.com/brianreborn/familia/issues/225), [#247](https://github.com/brianreborn/familia/issues/247)).
- Pull requests that ask Boundary, Race, and Platform to review, or name the Release Driver as the merger, without holding the merge for Brian ([#250](https://github.com/brianreborn/familia/pull/250), [#268](https://github.com/brianreborn/familia/pull/268), [#286](https://github.com/brianreborn/familia/pull/286), [#300](https://github.com/brianreborn/familia/pull/300), [#341](https://github.com/brianreborn/familia/pull/341), [#342](https://github.com/brianreborn/familia/pull/342), [#343](https://github.com/brianreborn/familia/pull/343), [#344](https://github.com/brianreborn/familia/pull/344)).

## Counts

| | |
|---|---|
| Open issues scanned | 148 |
| Open pull requests scanned | 17 |
| Included issues | 12 |
| Included pull requests | 9 |
| Included total | 21 |

Issue numbers: 70, 97, 190, 220, 221, 226, 234, 248, 278, 281, 283, 304.

Pull requests: 163, 164, 165, 166, 169, 170, 200, 249, 321.

## Next up / needs decision now

### [#190 — Rapid test build 2026-10-28](https://github.com/brianreborn/familia/issues/190)

- **Labels:** `priority:top`
- **Author:** brianreborn
- **Opened:** 2026-10-28
- **Updated:** 2026-10-28

**Summary.** Coordination issue for one tagged Linux test build (`test-2026-10-28b` at the time of writing). The body says no new feature merges until the next tag, and its PR triage table marks several items held for Brian.

**Latest relevant comments (2026-10-28).** Workers report the LFM3 first-time install passing, the pin bump landing, and a 14-task coding eval (LFM3-1.7B-Uncensored tool mode 9/14, plain chat 10/14). No later comment clears the triage table.

**Decision asked.** Say yes or no on the rows the table still marks held. In this repo those pull requests are still open: [#169](https://github.com/brianreborn/familia/pull/169) and [#164](https://github.com/brianreborn/familia/pull/164) (table: needs Brian's yes). [#170](https://github.com/brianreborn/familia/pull/170) is open and was marked out of the rapid scope. Drafts [#163](https://github.com/brianreborn/familia/pull/163), [#165](https://github.com/brianreborn/familia/pull/165), and [#166](https://github.com/brianreborn/familia/pull/166) were marked out. Familia #186, #187, and #176 are not open pull requests anymore. code-bootstraps-llama.cpp #45, #46, and #47 are named in the table and were not re-checked in that repo.

### [#321 — feat(android): one-tap Hermes webapp via cbl prebuilt + Termux:Widget](https://github.com/brianreborn/familia/pull/321)

- **Labels:** none
- **Author:** brianreborn
- **Opened:** 2026-11-05
- **Updated:** 2026-11-05
- **State:** ready for review (not draft)

**Summary.** Android one-tap Hermes path: code-bootstraps-llama.cpp arm64 prebuilt, license gate, RAM-tiered phone model, Termux:Widget launcher, webapp client. Opened from Brian's 2026-11-05 webapp-first direction.

**Latest relevant comments.**

- 2026-11-05, Grok Bot (round-5 fixes at `6b23578`): **product shape still pending Brian's choice.** A: phone opens the host Hermes webapp plus a local model for the offline llama-server UI. B: llama-server UI only. C: force 64k context. Lint fixture, early 64k refusal, and Termux-only key export were fixed in that round. Focused tests 51 passed; full suite 1345 passed with one known pre-existing failure.
- 2026-11-05, Issue watcher: lint and CodeQL passed on `6b23578`. Reads the standing webapp-first preference as **A**, and says the PR owner can align wording to A without a new chat ask. Galaxy A57 smoke stays blocked until a phone is online. This watcher does not merge.

**Decision asked.** Confirm A, or pick B or C. If A stands, no further product choice is pending on this PR beyond the phone smoke, which waits on a device rather than on a decision.

### [#249 — HVVRAM design-review package (pre-build, do not merge)](https://github.com/brianreborn/familia/pull/249)

- **Labels:** none
- **Author:** brianreborn
- **Opened:** 2026-10-31
- **Updated:** 2026-11-05
- **State:** draft

**Summary.** Docs only (`docs/vvram-ssd/HVVRAM-DESIGN-REVIEW.md`): nvso ABI 2 defects, an API sizing proposal, phases P0–P5 with decision points, and ZFS-on-Vertex-2 tuning. SSD firmware is deferred in the write-up.

**Latest relevant comments (2026-10-31).** Reviewers folded objections into rev 3. **D-PF0 is resolved** from Brian's note that day: do both ZFS and custom firmware, and unblock ZFS before the firmware. A Boundary review of the design doc was posted the same day. Nothing in the later comments approves P0–P5 for build.

**Decision asked.** Approve each remaining phase before anything is built or loaded. The PR says do not merge.

### [#283 — Handoff 8/8 (Team A → Team B): lead box fix branches, familia (10)](https://github.com/brianreborn/familia/issues/283)

- **Labels:** `handoff-team-b`
- **Author:** brianreborn
- **Opened:** 2026-11-02
- **Updated:** 2026-11-02

**Summary.** Release Driver handoff of 10 single-commit familia fix branches cut from `aa3339c` (behind `main` at the time). No comments on the issue. The body says to merge `main` into each branch, not rebase, and rerun tests.

**Decision asked.** Judgment call, and do not merge without it: on `fix/226-menu-internal` at `512804f`, 19 previously unlisted scripts were classified as **internal** (each with a reason in `scripts/menu-internal.txt`) instead of being added to the user menu, and documented in `docs/commands.md`. Confirm whether that user-facing versus internal split is right.

Secondary, because the box token lacked the `workflow` scope: `fix/218-ci-pytest` (`6b4b39b`) was not pushed. Push it with a token that can update `.github/workflows/`, or recreate the workflow from the GitHub UI. The described workflow runs pytest on pull requests and pushes to `main`, non-blocking (`continue-on-error`) until the open `test:` issues are green.

See [#226](https://github.com/brianreborn/familia/issues/226): a later comment says `main` already classified those scripts, so this branch may be redundant.

### [#226 — test: scripts missing from menu-items.txt and docs/commands.md](https://github.com/brianreborn/familia/issues/226)

- **Labels:** `from-other-grokbot`
- **Author:** brianreborn
- **Opened:** 2026-10-31
- **Updated:** 2026-11-01

**Summary.** `tests/test_menu.py` failed because many scripts were in neither `scripts/menu-items.txt` nor `scripts/menu-internal.txt`, and some commands were missing from `docs/commands.md`. CI only collected tests, so the failure was invisible.

**Latest comment (2026-11-01, Hermes Wiring).** Already fixed on `main` (`6f4c36b`) by `379203d` and `a0cf016`. Fresh `pytest tests/test_menu.py -k 'every_user_facing or commands_doc'` was 2 passed. No branch was opened. Suggests closing. This is Brian's call.

**Decision asked.** Close [#226](https://github.com/brianreborn/familia/issues/226), or keep it open. If you close it, [#283](https://github.com/brianreborn/familia/issues/283)'s confirmation on `512804f` is likely moot.

### [#221 — test: nodes miryam-pentest / angel-guardian card_set '5. Recommended settings' matches 0 card sets](https://github.com/brianreborn/familia/issues/221)

- **Labels:** `from-other-grokbot`
- **Author:** brianreborn
- **Opened:** 2026-10-31
- **Updated:** 2026-11-01

**Summary.** `harness2.py review` reported that `nodes.miryam-pentest` and `nodes.angel-guardian` used card set `5. Recommended settings`, which matched no sets on the linked card.

**Latest comment (2026-11-01, Hermes Wiring).** Already fixed on `main` (`6f4c36b`). The mradermacher model entry has no card sets; since `4723d0a` the nodes resolve to the RavichandranJ entry, which has that set. `python3 scripts/harness2.py --graph graph.yaml review` exited 0. Suggests closing. This is Brian's call.

**Decision asked.** Close [#221](https://github.com/brianreborn/familia/issues/221).

### [#220 — test: graph.yaml dolphin3-cyber-8b-q2k sha256 differs from model DB](https://github.com/brianreborn/familia/issues/220)

- **Labels:** `from-other-grokbot`
- **Author:** brianreborn
- **Opened:** 2026-10-31
- **Updated:** 2026-11-01

**Summary.** Graph validation rejected `models.dolphin3-cyber-8b-q2k` because sha256 `8944d35b…` did not match the mradermacher database entry (`966de378…`). That failure cascaded into harness, model-db, spec-draft, and RAM-safety tests.

**Latest comment (2026-11-01, Hermes Wiring).** Already fixed on `main`. The two hashes are two Hugging Face repos with the same filename. `graph.yaml` uses `8944d35b…` with `db:` pointing at RavichandranJ, which matches the registry. `4723d0a` repointed `db:` off the mradermacher entry. The cascading tests passed. `test_speculative_vocab_mismatch_and_ram` still failed on the box because the coder GGUF was missing, which is a separate cause. Suggests closing. The local-file sha still needs `activate_guardian_weights.py --measure` once weights are fetched, and that fetch waits on Brian.

**Decision asked.** Close [#220](https://github.com/brianreborn/familia/issues/220). Separately, say whether to fetch the guardian weights and run `--measure`.

### [#70 — Investigation: models for the CentOS Stream 10 big-RAM host](https://github.com/brianreborn/familia/issues/70)

- **Labels:** none
- **Author:** brianreborn
- **Opened:** 2026-10-19
- **Updated:** 2026-10-28

**Summary.** Model shortlist for the CentOS Stream 10 host with a GeForce 8600 GT. Doc mirror: `docs/perf/centos-bigram-models.md`. Early text assumed a much larger RAM size; that was corrected by measurement.

**Latest relevant comments.**

- 2026-10-20: measured i5-4570, 4 cores / 4 threads, AVX2, **23 GiB RAM** (not 64+), about 31–42 GB free disk, memcpy 9.8 GB/s. Dropped the 80B/120B-class ideas. Qwen3.5-2B about 11.75 tok/s gen, LFM2.5-1.2B about 23.0, gpt-oss-20b MXFP4 about 7.88 tok/s gen. **Role moves (coder and general onto this host) await the owner.**
- 2026-10-28, Platform Reviewer: branch `swarm/platform/centos-models-70`. Next step is a read-only host-fact probe once SSH reachability is known. No weight download until `licenses.py review` is OK.

**Decision asked.** From the open questions that the measurement comment did not close:

1. Confirm the proposed pass bar: generation at least 8 tok/s at 16K depth and prompt processing at least 30 tok/s for an interactive coder/general node.
2. Should this host take coder and general from miryam (about 7 GiB, so 2B-class), leaving miryam and the phones on decision and embed?
3. Which custom licenses are acceptable (LFM, OpenMDW, Tencent HY)?

### [#97 — Tracking: outstanding work 2026-10-19](https://github.com/brianreborn/familia/issues/97)

- **Labels:** none
- **Author:** brianreborn
- **Opened:** 2026-10-20
- **Updated:** 2026-10-20

**Summary.** Checklist of outstanding work as of 2026-10-19. No comments. Most bullets are engineering follow-ups. One section is explicitly waiting on the administrator, and every box in it is still unchecked.

**Decision asked.** The "Decisions awaiting user" list:

- [ ] driver strategy
- [ ] role moves (coder + general to the CentOS box) — same question as [#70](https://github.com/brianreborn/familia/issues/70)
- [ ] move graph.yaml host addresses and usernames to a private override
- [ ] second phone
- [ ] where Virtue/MXOS live
- [ ] Routing Test Designer agent created; no first task yet

The P1 line "[ ] #94 forgejo crash loop (needs approval)" is stale relative to [#94](https://github.com/brianreborn/familia/issues/94): on 2026-10-28 Platform Reviewer took that issue and is blocked on host reachability, not on a fresh approval.

## Waiting on admin review

These have a described patch or an open pull request, and the remaining gate in the thread is Brian's yes to push or merge.

### [#169 — fix(race): miryam coder CPU prefer + ngram opt-in (#83/#82)](https://github.com/brianreborn/familia/pull/169)

- **Labels:** none
- **Author:** brianreborn
- **Opened:** 2026-10-28
- **Updated:** 2026-11-05
- **State:** ready for review

**Summary.** Prefer a CPU runtime when `-ngl 0`, hide Vulkan for that child, and make `ngram-simple` opt-in (`speculative.coder-ngram` set to `planned`, default spec type `ngram-mod`). Body: do not merge without Brian's yes. Named in [#190](https://github.com/brianreborn/familia/issues/190) as held.

**Latest comments.** 2026-10-28: rebased onto `main` as `229fd14` on `swarm/race/miryam-perf`, holding for Brian's exact yes. 2026-11-05, Race review at `229fd14`: **APPROVE with nits** (bin/lib swap between the platform check and process start).

**Decision asked.** Merge yes or no for [#169](https://github.com/brianreborn/familia/pull/169).

### [#170 — feat(race): draft-simple speculative decoding seatbelts (#91)](https://github.com/brianreborn/familia/pull/170)

- **Labels:** none
- **Author:** brianreborn
- **Opened:** 2026-10-28
- **Updated:** 2026-11-05
- **State:** ready for review

**Summary.** Opt-in draft-model speculative decoding. `coder-draft` stays `planned`. Seatbelts refuse a missing draft GGUF and over-thread the sprint cap. Body: do not merge without Brian's exact yes. [#190](https://github.com/brianreborn/familia/issues/190) marked it out of the rapid-build scope. It is still explicitly held.

**Latest comment (2026-11-05, Race review at `b7b8ebd`).** **APPROVE with nits.** Draft loads in-process (`-md`), so there is no orphan draft server.

**Decision asked.** Merge yes or no for [#170](https://github.com/brianreborn/familia/pull/170).

### [#248 — R5: session RLock is not FIFO; per-session reply order breaks under contention](https://github.com/brianreborn/familia/issues/248)

- **Labels:** `priority-1`
- **Author:** brianreborn
- **Opened:** 2026-10-31
- **Updated:** 2026-11-04

**Summary.** Per-session ordering used `threading.RLock`, which is not fair. Later findings: `FairLock` on `main` already grants in accept order ([#254](https://github.com/brianreborn/familia/issues/254)). The remaining failure is the test, which opens one connection per thread, so the client can reorder connects before accept.

**Latest comment (2026-11-04, Hermes Wiring).** Test-only branch `fix/r5-fifo-test-248` (four commits on `d62d79a`: `ff89594`, `d69728f`, `1bfb4de`, `e0786be`) changes only `tests/test_race_routing.py`. Platform and Race both approved. 19 tests in the file passed; Race saw 0 flakes in 40 loaded runs. Patch was left at `/workspace/review/248.patch` on the shared box. **Not pushed. Waiting for Brian's per-push OK.**

**Decision asked.** Approve pushing `fix/r5-fifo-test-248`.

### [#234 — test: Windows/pwsh/man/groff tests always skipped on Linux](https://github.com/brianreborn/familia/issues/234)

- **Labels:** `from-other-grokbot`
- **Author:** brianreborn
- **Opened:** 2026-10-31
- **Updated:** 2026-11-04

**Summary.** Windows, man, and groff tests skip on Linux because `pwsh`, `man`, and `groff` are absent, so those paths never run in CI.

**Latest comment (2026-11-04, Hermes Wiring).** Local branch `fix/ps51-install-234` at `655ada7` (base `5da1d33`). Windows PowerShell 5.1 reads a BOM-less `.ps1` as cp1252, so box-drawing bytes in `familia-home.ps1` and `setup-goals.ps1` are parsed as quotes. Fix: UTF-8 BOM on all 27 `.ps1` files, plus `test_ps1_files_have_utf8_bom_for_windows_powershell_51`, which runs on Linux. **Branch not pushed; waiting for Brian's per-push OK.** A real `powershell.exe -NoProfile -File install\windows\install.ps1 -WhatIf` on Windows is still open.

**Decision asked.** Approve pushing `fix/ps51-install-234`.

### [#281 — Handoff 6/8: Fuzz Tester nexus_localhost tmp fix needs a disposable host](https://github.com/brianreborn/familia/issues/281)

- **Labels:** `handoff-team-b`
- **Author:** brianreborn
- **Opened:** 2026-11-02
- **Updated:** 2026-11-04

**Summary.** Branch `fix/fuzz-tmp-nexus-localhost-main` at `8b34e2a` replaces the fixed `/tmp/nexus-test` directory (which the script `sudo rm -rf`'d) with `mktemp -d`. The script needs sudo, local users, and a throwaway sshd, so it must run on a disposable VM. It overlaps `fix/219-shellcheck` (`7555bb0`).

**Latest comment (2026-11-04, Fuzz Tester).** Claim approved by Brian. A private `TMPDIR` can hide the work dir from the test users. Local patch, rebased on `main`, uses `/tmp/nexus-test.XXXXXXXX` and keeps `$(command -v bash)`. Shellcheck-clean. Signal test: `rc=143`, temp dir gone, sshd not left alive. End-to-end with real sudo and users is still not run. **Nothing pushed; a push waits on Brian's per-push OK.**

**Decision asked.** Approve pushing that rebased patch. The disposable-VM run is still required before merge; the push itself is what is waiting on you.

### [#278 — Handoff 3/8: HF cache-coherent resumable downloads (hf_cache.py)](https://github.com/brianreborn/familia/issues/278)

- **Labels:** `handoff-team-b`
- **Author:** brianreborn
- **Opened:** 2026-11-02
- **Updated:** 2026-11-03

**Summary.** Branch `release/llama-bump-hf-cache` at `1e13eb9`, pushed 2026-11-01. Despite the name, the branch is only the HF cache work (`scripts/hf_cache.py`, `hf_fetch.py` delegating to it, `tests/test_hf_cache.py`): ETag revalidation, ranged resume, sha256 before rename, and an exclusive lock. Box run on 2026-11-01: 8 tests passed. No open pull request in familia matches this branch.

**Latest comment (2026-11-03, code-bootstraps agent).** Branch rebased on `main`, tests run, **PR opening with Brian's OK.**

**Decision asked.** Approve opening the pull request for `release/llama-bump-hf-cache`.

### [#304 — L14 (Low): graph_router sends node bearer keys over plain HTTP to opted-in remote nodes](https://github.com/brianreborn/familia/issues/304)

- **Labels:** none
- **Author:** brianreborn
- **Opened:** 2026-11-05
- **Updated:** 2026-11-05

**Summary.** On `main` at `f743d0e`, `scripts/graph_router.py` builds `http://` upstream URLs and sends `Authorization: Bearer` for remote opted-in nodes. Loopback is unaffected. Filed with Brian's OK on 2026-11-04 as a v0.3 item. Fix options in the body: (1) document the risk and warn at startup, (2) allow `https://` and verify the certificate, (3) SSH-tunnel so the key stays on loopback.

**Latest comment (2026-11-05, Issue watcher).** L14 still matches current `main`. Recommended next step is option 1 only (docs plus a startup warning). **Will open a branch and pull request only after Brian's per-push OK.** The same comment says [#314](https://github.com/brianreborn/familia/issues/314) / [#303](https://github.com/brianreborn/familia/issues/303) were waiting on a rebase-push OK; those two issues are not open now.

**Decision asked.** Approve opening the option-1 branch (warning and docs, no protocol change).

## Other open

Draft pull requests whose body says not to merge without Brian's exact yes. No review comments were on them at scan time. [#190](https://github.com/brianreborn/familia/issues/190) marked the three design drafts as outside the 2026-10-28 rapid build.

### [#164 — feat(monitor): one-command pinned probe deploy](https://github.com/brianreborn/familia/pull/164)

- **Labels:** none
- **Author:** brianreborn
- **Opened:** 2026-10-28
- **Updated:** 2026-11-05
- **State:** draft

**Summary.** `scripts/monitor/deploy-probe.sh` and `familia-monitor --deploy-probe` copy the pinned probe into `~/.local/share/familia/`. One slice of [#71](https://github.com/brianreborn/familia/issues/71). Live tok/s, Hermes relay alerts, and a live Windows/Termux probe stay open on that issue. Held in the [#190](https://github.com/brianreborn/familia/issues/190) table.

**Decision asked.** Merge yes or no. The PR says do not merge without Brian's exact yes.

### [#200 — test(routing): #199 router no-op catalogue + routing test suite](https://github.com/brianreborn/familia/pull/200)

- **Labels:** none
- **Author:** brianreborn
- **Opened:** 2026-10-31
- **Updated:** 2026-11-05
- **State:** draft

**Summary.** Tests and a findings doc for [#199](https://github.com/brianreborn/familia/issues/199). Offline fake loopback nodes. Reported 8 passed and 18 strict xfails. No product code. Body: do not merge without Brian's exact yes.

**Decision asked.** Merge yes or no for the test suite.

### [#163 — docs(design): Jev harness slimming next steps](https://github.com/brianreborn/familia/pull/163)

- **Labels:** none
- **Author:** brianreborn
- **Opened:** 2026-10-28
- **Updated:** 2026-11-05
- **State:** draft

**Summary.** Design note `docs/design/jev-harness-slimming.md` for [#89](https://github.com/brianreborn/familia/issues/89). Related to the measurement already described in `docs/harness-slimming.md`.

**Decision asked.** Merge yes or no. Exact yes required by the PR body.

### [#165 — docs(design): Terminal-RSI scaffolding](https://github.com/brianreborn/familia/pull/165)

- **Labels:** none
- **Author:** brianreborn
- **Opened:** 2026-10-28
- **Updated:** 2026-11-05
- **State:** draft

**Summary.** Design note `docs/design/terminal-rsi.md` (trajectory, refine, gate) for [#88](https://github.com/brianreborn/familia/issues/88) and [#68](https://github.com/brianreborn/familia/issues/68). Implementation is deferred in the PR.

**Decision asked.** Merge yes or no. Exact yes required by the PR body.

### [#166 — docs(design): Harness² integration scaffolding](https://github.com/brianreborn/familia/pull/166)

- **Labels:** none
- **Author:** brianreborn
- **Opened:** 2026-10-28
- **Updated:** 2026-11-05
- **State:** draft

**Summary.** Design note `docs/design/harness2-integration.md` for [#87](https://github.com/brianreborn/familia/issues/87) and [#65](https://github.com/brianreborn/familia/issues/65). Points at `scripts/harness2.py` and `docs/harness2.md`. Live dogfood loops are left to Hermes wiring.

**Decision asked.** Merge yes or no. Exact yes required by the PR body.
