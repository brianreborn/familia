# Familia v0.3.0 sprint plan

Updated: 2026-11-10 3:35 PM PT (America/Los_Angeles)

This is the current v0.3.0 sprint plan. It is new on main (SPRINT.md was
not on main; the 2026-11-02 list lives only on open PR #286 and is stale).
After this PR merges, close #286 as superseded.

## Rules

- v0.3.0 work never uses the development branch. All 0.3.0 branches and
  PRs target main only. Open PRs still based on development (#370, #363)
  should be retargeted or reopened against main.
- Merges need two valid reviews. Signed reviewer comments count as
  reviews. Only risky PRs go to Brian. No force push.
- The hot-file freeze was lifted by Brian at 3:25 PM PT on 2026-11-10.
  Menu code, graph.yaml, protograph, model picking, and the formerly
  frozen files (familia_home.sh, proto_chat.sh, open_ui.sh, ui_bridge.py,
  menus, FreeBSD/Termux docs, and issues #327-331) may proceed against
  main.
- ASCII only in this file (plain ASCII glyphs; no Unicode decoration).

## 1. Landed 2026-11-10 (do not redo)

- Coordinator-free pull swarm design: PR #380 merged to main at d997acd.
  https://github.com/brianreborn/familia/pull/380
- ASCII/ANSI style guide: PR #381 merged to main at 8babfd4.
  https://github.com/brianreborn/familia/pull/381
- Routing boundary tests: PR #362 went through development (merged
  there at 6ce6adf) before the main-only rule, and is now on main at
  3934b39. Residual nits and TR-3/TR-4 still open.
  https://github.com/brianreborn/familia/pull/362
- Self-hosted runners are online and passed smoke jobs (angel,
  galaxy1, galaxy2). Runner labels, host inventory, and M17
  owner-settings detail live in #236, not in this public file.
  Angel smoke: https://github.com/brianreborn/familia/actions/runs/42921698653
  Phone smoke: https://github.com/brianreborn/familia/actions/runs/42921763422
- Phone liveness: the A57s share about 7 GB RAM with a resident
  model (qwen on galaxy1, LFM3 on galaxy2) plus the #367 SSH smoke.
  Keep one job per phone. The SSH smoke must take the same per-phone
  lock. Label a phone as serving when its model is resident.
- Angel coder selection (not serving yet): Qwen2.5-Coder 3B 4-bit with
  Qwen2.5-Coder 0.5B as the draft model. No large models on FreeBSD.

## 2. Release blockers: FreeBSD 42 test failures

Parent: https://github.com/brianreborn/familia/issues/387
Pass condition for each: the test passes on angel's runner without
breaking Linux. Owner for investigation: unassigned swarm runners
(prefer angel). Record fixes in issues and PRs against main.

- #396 FIRST: host-local ~/ci/run-familia-ci.sh on angel (tee at
  lines 164-165 swallows pytest's exit status; START_HUMAN unset at
  line 455). Greens from that script are untrustworthy until this is
  fixed. The script is not in the repo. Angel's github-act-runner
  jobs run workflow steps (checkout, pytest, and similar), not this
  script (verified in Actions run 42921698653; angel-smoke.yml is
  not in this PR or on main). Status: open.
- #387 parent: FreeBSD 42 test failures block 0.3.0. Status: open.
- #388 path resolution: familia-start refuses test key files (~15 tests).
- #389 Windows reserved names not rejected (COM/LPT superscripts,
  CONIN$/CONOUT$; 9 tests).
- #390 hermes-agent PATH shadow and /usr group-writable trust checks
  (9 tests).
- #391 missing registry/llama-builds flag tables under FAMILIA_SYNC=0.
- #392 test_bench_idle nice off-by-one (20 == 19).
- #393 hostile hop test hits HTTP 502 (related to PR #362). The
  issue now says land on main (0.3.0 work targets main). The
  morning pin predates #362 (a4a65b3, now on main at 3934b39).
  Re-run the test on angel at main after #362 before rewriting it.
- #394 test_hermes_upstream_compat KeyError GITHUB_TOKEN.
- #395 test_windows Activate.ps1 UTF-8 BOM on host venv.
- graph.yaml still names Nanbeige4.3-33B Q4_K_M as angel-coder on
  angel, which conflicts with the no-large-models-on-FreeBSD rule
  and Brian's choice of Qwen2.5-Coder 3B 4-bit with a 0.5B draft.
  The sprint line is the intended change; fix graph.yaml in a
  separate PR.
- a57-ssh-smoke.yml is still gated to development and needs
  retargeting to main. 0.3.0 pushes to main will not run that SSH
  smoke until the workflow is retargeted (or ci/a57-capability-smoke
  is merged to main). Do not change workflows in this PR.

## 3. New product work (2026-11-10)

The hot-file freeze was lifted at 3:25 PM PT on 2026-11-10. Menu,
protograph, graph.yaml, and model-picking work may proceed against
main.

- #397 App catalog: virtual app store menu item; public search of open
  issues labeled applications, with a local cache.
  https://github.com/brianreborn/familia/issues/397
  Owner: grokbot (box). Status: claimed:grokbot at 3:26 PM PT
  on 2026-11-10. Blocker: none (freeze lifted).
- #398 Menu: intelligent model picking.
  https://github.com/brianreborn/familia/issues/398
  Owner: grokbot (box). Status: claimed:grokbot at 3:26 PM PT
  on 2026-11-10. Blocker: none (freeze lifted).
- #399 Proto model / protograph skill for configuring graph.yaml.
  https://github.com/brianreborn/familia/issues/399
  Related: #327-331. Owner: grokbot (box). Status: claimed:grokbot
  at 3:26 PM PT on 2026-11-10. Blocker: none (freeze lifted).
- #327-331 per-host menu redesigns (angel, galaxy1, galaxy2,
  reference). Code may start against main; keep one owner per issue
  so two agents do not take the same one.

## 4. Transport-agnostic swarm (no extra LAN/WAN required)

Design is transport-agnostic: SMS, MMS, Wi-Fi Direct, Bluetooth, or
existing LAN should all plug into one layer. No real SMS until Brian
confirms both phones' numbers. Ask before changing Bluetooth pairing.
Claim repo brianreborn/familia-claims does not exist; creating it is
ask-first.

- #382 parent: transport-agnostic local coordination. Status: open,
  unclaimed. https://github.com/brianreborn/familia/issues/382
- #383 galaxy1 Wi-Fi Direct (root-free Termux/Android P2P).
  Status: claimed:galaxy1.
  https://github.com/brianreborn/familia/issues/383
- #384 galaxy2 SMS/MMS (termux-api, limits, signed envelopes).
  Status: claimed:galaxy2.
  https://github.com/brianreborn/familia/issues/384
- #385 miryam Bluetooth (BlueZ RFCOMM/BLE GATT to phones).
  Status: claimed:miryam.
  https://github.com/brianreborn/familia/issues/385
- #386 angel transport abstraction + LAN baseline (lossy-link leases,
  BT dongle). Status: claimed:angel.
  https://github.com/brianreborn/familia/issues/386
- #380 follow-up docs (Platform Reviewer nits, not blockers):
  prefer a GitHub App over a machine user; token limited to
  refs/claims/* does not exist (use a ruleset); say which repo the
  fallback Issues: write applies to and that it never includes
  Actions/Workflows; compare the actor numeric id, not login, in the
  /run gate; cite GraphQL updateRefs beforeOid as atomic; document
  phone token handling (Termux $HOME 0600, pass by file, expiry and
  rotation, App key never on a phone, token broker host).
  Owner: docs follow-up PR against main. Blocker: Brian OK to create
  brianreborn/familia-claims (needs at least one commit before refs).

## 5. Runners, models, and benchmarks

- Phone runners last only while Termux stays open. Termux Boot is
  needed to survive a reboot; needs Brian's OK. Status: waiting.
  Liveness (same as section 1): one job per phone; #367 SSH smoke
  takes the same per-phone lock; label a phone as serving when its
  model is resident. The phones share about 7 GB with resident
  LFM3/qwen plus that smoke.
- ci/a57-capability-smoke branch is unmerged; manual Actions starts
  need that merge (against main).
- Angel coder is not serving yet. Start in screen session coder-angel
  once a working FreeBSD llama.cpp server exists. Do not restart an
  already-running server; do not touch the NTFS disk.
- #183 TOP PRIORITY: performance-test all models on real suites
  (HumanEval, MBPP, MMLU, tokens/s) plus deployment topology.
  Charts/PR intended in familia-private under bench/2026-11-10/.
  In progress on miryam (screen bench-report), low priority.
  Target around 3:48 PM PT, partial results marked if needed.

## 6. Security and review follow-ups

Tracker: https://github.com/brianreborn/familia/issues/236

- L13: tmp-file issue; open until code-bootstraps-llama.cpp #93 merges.
  https://github.com/brianreborn/code-bootstraps-llama.cpp/pull/93
- L14: node keys over plain HTTP; startup warning landed in #374.
- L15: ui_bridge.py prints unstripped control characters (same class
  as #303). The hot-file freeze was lifted at 3:25 PM PT; code may
  proceed against main. Status: open.
- M17 (Medium, extends M6): miryam self-hosted runner reachability
  to the A57s via the #367 dispatcher key. Owner-only GitHub
  settings; details in #236, not in this public file.
  https://github.com/brianreborn/familia/issues/236#issuecomment-6774972991
  M17 status: see #236.
  Self-hosted workflows merging to main are gated on M17 settings first.
- TR-3 residual: normalize_role should strip/Cf and reject non-ASCII
  or unknown roles (padded names, zero-width, lookalikes). TR-4
  role-override gap. Status: product issue not filed. Owner:
  Senior Developer (filing). Boundary Reviewer reviews.
- #362 nits (non-blocking): POSIX skipif in test_race_routing.py
  should be scoped to the fork test only; Windows pytestmark skips
  the whole race file; R1 fork()s a threaded process. #362 itself
  went through development before the main-only rule.

## 7. Worker line items (familia / 0.3.0)

Format: owner | work | link | status | blocker

- qodesh Worker | Read-only PowerShell 5.1 smoke for draft PR #300
  (parse install.ps1, dry-run, Uninstall/Purge refuse without
  marker); post signed results. #305 already merged 2026-11-06.
  Also: confirm /usr/tmp/ctxsmoke cleanup on the A57s; align
  /workspace/session/android-installer/ with the Hermes Wiring
  smoke; older #227/#232. | https://github.com/brianreborn/familia/pull/300 | queued | Needs Brian local-exec OK per run; check disk FS state first. Hosts were offline on 2026-11-06; LAN is back.
- Hermes Wiring | Reconcile seven local Android/guardian commits
  with open PR #321 without overwriting its eight commits (rebase
  onto #321 or a new draft branch). HVVRAM kernel defects confirmed
  only by static review; FreeBSD runtime still unverified. | https://github.com/brianreborn/familia/pull/321 | blocked on approach choice | Brian chooses rebase onto #321 vs a separate draft branch. No force push.
- Continuity | Keep #300 Windows installer moving (draft, closes
  #32). sysrescue bootmgr repair was completed later by qodesh
  Worker. | https://github.com/brianreborn/familia/pull/300 | draft open | Needs PS 5.1 results and reviews.
- Senior Developer | Track remaining #236 items (L13/L15/M17) and
  file the TR-3/TR-4 product issue (Boundary Reviewer reviews it).
  Daily 10 AM PT security check-in stays running (Brian said keep
  it). | https://github.com/brianreborn/familia/issues/236 | open | L15 freeze lifted; M17 is owner-only GitHub settings.
- Researcher | Coordinate 0.3.0 work onto main; do not start new
  development branches. Windows-only relocation remains a separate
  ops thread, not this sprint. | (coordinator) | idle since 2026-11-10 check-in relay | none for sprint coordination.
- Release Driver | A57 chat model chosen 2026-11-06:
  LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf (install OK was still pending
  then; galaxy2 now serves LFM3). Help start angel's coder-angel
  session when llama.cpp is ready. | (host deploy) | partial | Brian per-host install OK if anything new is copied to a phone.
- Platform Reviewer | Review the #380 follow-up docs PR (nits 1-6)
  and later 0.3.0 PRs against main. Just approved #380 and was
  re-reviewing #362 (now merged). | https://github.com/brianreborn/familia/pull/380#issuecomment-6781869353 | nits open | familia-claims repo needs Brian OK.
- Boundary Reviewer | Review the TR-3/TR-4 product issue (Senior
  Developer files it); review 0.3.0 PRs against main. Approved
  #362. | https://github.com/brianreborn/familia/pull/362#issuecomment-6781949185 | nits + owed issue | none.
- Race Reviewer | #362 nits (Windows pytestmark, R1 fork of a
  threaded process). Re-review #169/#170 if they stay on main.
  Update those branches by merging main in (no rebase and no
  force push). | https://github.com/brianreborn/familia/pull/362#issuecomment-6781993525 | nits; #169/#170 still open | standing review-fix push OK covers merging main in; no rebase/force push.
- Fuzz Tester | #281 nexus localhost tmp fix 8b34e2a needs a
  real-user run on a disposable host; overlap check. Five
  unresolved Green-Roomz fuzz bugs remain (null-body hangs,
  Unicode/speech 500s, null mailbox crashes, env-path expansion).
  Lockdown/reboot stayed blocked (good).
  | https://github.com/brianreborn/familia/issues/281 | waiting | Needs a disposable host from Brian.
- Covert Channel Fixer | Next green-roomz fix-pack items after
  SSE/ESC strip (P0b constant-time secureEquals, P0c log/path
  scrubbing, P1 no cache_prompt reuse across tenants). familia
  :9931 key-fix review still listed.
  | green-roomz (no open PRs at last check) | local/unpushed as of 2026-11-06 | Brian push OK and which tree is canonical for v0.3.
- Covert Channel Reviewer | Post-land re-check of 8731d03 and
  tool_calls name/arguments strip. | (review) | idle | Depends on Fixer landing the follow-up.
- Bootstraps Reviewer | Review cbl #90/#91/#93 (L13). familia #370
  is an approve in draft, not posted (widget unanswered); if kept,
  retarget #370 to main.
  | https://github.com/brianreborn/code-bootstraps-llama.cpp/pull/93 | waiting | Brian OK to post the #370 comment; #370 base is development.
- MeshForge Lead | Unpushed familia patches (#32 r5 into #300, and
  related) as of 2026-11-06; MeshForge research stays outside this
  sprint except where it supports familia Android thin-client
  shape.
  | https://github.com/brianreborn/familia/pull/300 | unpushed/check current | Push only with standing review-fix OK or a new OK.
- Other Grok Bot ASSIST | Coordinate worker wakes and keep this
  plan current. Already handling the 2026-11-10 voice-call
  workstream. | this PR | in progress | none.
- code-bootstraps bot | Land cbl #90/#91/#93 on main (security log
  redaction; L13).
  | https://github.com/brianreborn/code-bootstraps-llama.cpp/pull/93 | open | reviews.
- Bootstraps Coding Evaluator and Click-and-Go Tester | Resume
  default-set coding/out-of-box tests when the 0.3.0 model matrix
  (phones + angel coder) is serving. | cbl default set | idle | models must be up; no micro-benchmark sweeps.
- Note9 Release | Android release track (#203, #321, #277 ALPHA
  install). | https://github.com/brianreborn/familia/issues/203 | open | #321 needs reconcile; #277 is spec-only.
- RT Scout | No new 0.3.0 implementation work. Two drafted
  refinement comments (familia #310, green-roomz #44) still need
  Brian's yes to post. | https://github.com/brianreborn/familia/issues/310 | parked | Brian approval to post.

## 8. Open PRs still targeting familia (retarget note)

Against main (keep, do not move to development):

- #321 Android packaging (needs reconcile; see Hermes Wiring).
- #300 Windows Uninstall/Purge (draft; closes #32).
- #286 stale SPRINT.md (close after this PR merges).
- #268 routing graph UX.
- #250 L-hostloc lessons (docs; left earlier as risky).
- #249 HVVRAM design-review (draft; do not merge).
- #200 router no-op tests (draft; #199).
- #170 speculative-decoding seatbelts. Update by merging main in
  (no rebase and no force push).
- #169 miryam coder CPU prefer + ngram opt-in. Update by merging
  main in (no rebase and no force push).
- #166 #165 #164 #163 drafts (Harness2, Terminal-RSI, monitor, Jev).

Against development (retarget or reopen onto main for 0.3.0):

- #370 PyYAML/pytest dev deps (#175).
- #363 hermes userinfo scrub (Boundary #354 nit).

## 9. Carryover still open from the 2026-11-02 list

These stayed open and remain in scope if they affect 0.3.0. Many
handoff items (#277-283) are stale relative to later merges; re-check
before starting.

- #203 bulletproof small-device deployment (epic).
- #277 ALPHA unattended install / license gate (spec only; new branch
  from main).
- #32 / #300 Windows installer.
- #234 Windows/pwsh tests skipped on Linux.
- #227 familia-menu.sh --pipe hang; #232 start.sh --yes screen timeout.
- #199 router no-op R&D (#200 draft).
- #293 install.sh has no published SHA256SUMS.
- #295 OOM-killer relax / soft limits; #307 miryam LFM3 thread tuning.
- #323 FreeBSD RACCT/RCTL proposal (docs freeze lifted; work against
  main if it touches FreeBSD docs).
- #332 Android offline handling.
- #377 X-interaction intake doc/tracker inconsistencies.
- #368 / #365 HVVRAM integration (design; do not block the release).
- Team A->B handoffs #278-283: re-audit; do not assume branches are
  current.
- cbl #90/#91/#93 as above. Older cbl Android leftovers (#13) and
  Windows parity (#11, #14, #32) may still apply.

## 10. Non-familia work found (not in this sprint)

List only. Do not wake these bots for 0.3.0 unless Brian asks.

- Posts Worker: read-only X research for papers.
- Twitter Janitor: X account hygiene; posting still on HOLD.
- Writer: writing lane.
- Paper Worker: water-spinach paper published; linguistics paper is
  seed-only.
- Junior Repair A and B: Urara kindness repairs on HOLD.
- Kindness Protocol: playbook only; posts need Brian OK.
- X Bug Cartographer: X platform bugs.
- Hope Wave Scout: pass 2 of the Haru Urara brief not done.
- Visibility Reciprocity: X visibility research.
- Urara Epitaph: epitaph book.
- X research -> skill: skill work (group channel).
- Twitch CDN Recoverer and Twitch Takedown Tracer: electrobrains VOD
  forensics (read-only).
- Forensic Investigator: auth audit v3 PDF ready; sudo -n blocked on
  miryam/angel; not 0.3.0 code.
- Emergency Asylum: no assignment.
- New Bot: no assignment.
- miryam Camera Watch: local camera snapshots.
- Review Board Viewer: curate /workspace/reviews (green-roomz #39
  still needs Brian policy calls).
- Security Review: group channel; no recent 0.3.0 claim found.
- MeshForge Lead research on NVIDIA OpenShell / office-3d stays in
  the MeshForge repo except as noted in section 7.

## 11. Sources

- Main on 2026-11-10: ROADMAP.md is still the v0.2.0 roadmap, and
  SPRINT.md is still absent on main. The v0.3.0 milestone exists
  (milestone 1). docs/HANDOFF.md is the 2026-10-10 resume index.
- Stale plan: PR #286 (docs/current-sprint-2026-11-02, 2026-11-02).
- Worker transcripts and 2026-11-06 local-transition checkpoints
  under /workspace/session/local-transition-2026-11-06/.
- Live GitHub issues/PRs and claims as of 2026-11-10 3:35 PM PT.
- Review fixes from Race, Boundary, and Platform on PR #400
  (comments 6782152898, 6782156531, 6782249291, 6782251389,
  and 6782273617).
