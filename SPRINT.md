# Familia v0.3.0 sprint plan

Updated: 2026-11-10 3:23 PM PT (America/Los_Angeles)

This is the current v0.3.0 sprint plan. It is new on main (SPRINT.md was
not on main; the 2026-11-02 list lives only on open PR #286 and is stale).
After this PR merges, close #286 as superseded.

## Rules

- v0.3.0 work never uses the development branch. All 0.3.0 branches and
  PRs target main only. Open PRs still based on development (#370, #363)
  should be retargeted or reopened against main.
- Merges need 3+ signed reviews. No force push.
- Hot-file freeze: do not edit familia_home.sh, proto_chat.sh, open_ui.sh,
  ui_bridge.py, menus, graph.yaml, FreeBSD/Termux docs, or issues #327-331
  until Brian lifts the freeze. Track the work here; hold the code.
- ASCII only in this file (plain ASCII glyphs; no Unicode decoration).

## 1. Landed 2026-11-10 (do not redo)

- Coordinator-free pull swarm design: PR #380 merged to main at d997acd.
  https://github.com/brianreborn/familia/pull/380
- ASCII/ANSI style guide: PR #381 merged to main at 8babfd4.
  https://github.com/brianreborn/familia/pull/381
- Routing boundary tests: PR #362 merged to development at 6ce6adf
  (auto-merge to main follows). Residual nits and TR-3/TR-4 still open.
  https://github.com/brianreborn/familia/pull/362
- Self-hosted runners are online and passed smoke jobs:
  - angel: github-act-runner 0.13.0, runner 23, labels self-hosted, X64,
    freebsd, amd64, cpu, ram-24g, angel. Screen: screen -r ci-angel.
    Test: https://github.com/brianreborn/familia/actions/runs/42921698653
  - galaxy1: familia-a57-qwen, runner 24, labels self-hosted, android,
    arm64, a57, termux, ram-7g, qwen. Screen: screen -r ci-galaxy1.
  - galaxy2: familia-a57-lfm, runner 25, same labels except lfm. LFM3
    kept running. Screen: screen -r ci-galaxy2.
  Phone job: https://github.com/brianreborn/familia/actions/runs/42921763422
- Angel coder selection (not serving yet): Qwen2.5-Coder 3B 4-bit with
  Qwen2.5-Coder 0.5B as the draft model. No large models on FreeBSD.

## 2. Release blockers: FreeBSD 42 test failures

Parent: https://github.com/brianreborn/familia/issues/387
Pass condition for each: the test passes on angel's runner without
breaking Linux. Owner for investigation: unassigned swarm runners
(prefer angel). Do not edit frozen FreeBSD docs; record fixes in
issues and code-only PRs against main.

- #387 parent: FreeBSD 42 test failures block 0.3.0. Status: open.
- #388 path resolution: familia-start refuses test key files (~15 tests).
- #389 Windows reserved names not rejected (COM/LPT superscripts,
  CONIN$/CONOUT$; 9 tests).
- #390 hermes-agent PATH shadow and /usr group-writable trust checks
  (9 tests).
- #391 missing registry/llama-builds flag tables under FAMILIA_SYNC=0.
- #392 test_bench_idle nice off-by-one (20 == 19).
- #393 hostile hop test hits HTTP 502 (related to PR #362).
- #394 test_hermes_upstream_compat KeyError GITHUB_TOKEN.
- #395 test_windows Activate.ps1 UTF-8 BOM on host venv.
- #396 run-familia-ci.sh reports PASS when pytest failed (tee exit
  code at lines 164-165; START_HUMAN unset at line 455). Status: open.
  Blocker: none; script lives on angel at ~/ci/run-familia-ci.sh and
  was not edited when found.

## 3. New product work (2026-11-10)

Code for menu, protograph, and graph.yaml waits on the hot-file freeze.

- #397 App catalog: virtual app store menu item; public search of open
  issues labeled applications, with a local cache.
  https://github.com/brianreborn/familia/issues/397
  Owner: unassigned. Status: filed, not claimed. Blocker: freeze
  (menus).
- #398 Menu: intelligent model picking.
  https://github.com/brianreborn/familia/issues/398
  Owner: unassigned. Status: filed. Blocker: freeze (menus).
- #399 Proto model / protograph skill for configuring graph.yaml.
  https://github.com/brianreborn/familia/issues/399
  Related: #327 (frozen). Owner: unassigned. Status: filed.
  Blocker: freeze (graph.yaml, menus, #327-331).
- #328-331 frozen menu redesigns (angel, galaxy1, galaxy2, reference).
  Do not start code until the freeze lifts.

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
  as #303). Code is hot-frozen. Status: open, hold code.
- M17 (Medium, extends M6): miryam self-hosted runner can reach A57
  phones via the #367 dispatcher key. Fixes are owner-only settings:
  approve all external contributor workflows; protect main (and stop
  using development for 0.3.0); dedicated phone CI key with
  restrict,command=; ephemeral/containerized runner. Not checked:
  whether the key is already on miryam.
  https://github.com/brianreborn/familia/issues/236#issuecomment-6774972991
- TR-3 residual: normalize_role should strip/Cf and reject non-ASCII
  or unknown roles (padded names, zero-width, lookalikes). TR-4
  role-override gap. Status: product issue not filed. Owner: Boundary
  Reviewer / Senior Developer. Blocker: none to file the issue.
- #362 nits (non-blocking): POSIX skipif in test_race_routing.py
  should be scoped to the fork test only; Windows pytestmark skips
  the whole race file; R1 fork()s a threaded process.

## 7. Worker line items (familia / 0.3.0)

Format: owner | work | link | status | blocker

- qodesh Worker (0af4492c-5094-462f-b47b-9efcedecf20f) | Read-only
  PowerShell 5.1 smoke for draft PR #300 (parse install.ps1, dry-run,
  Uninstall/Purge refuse without marker); post signed results. #305
  already merged 2026-11-06. Also: confirm /usr/tmp/ctxsmoke cleanup
  on the A57s; align /workspace/session/android-installer/ with the
  Hermes Wiring smoke; older #227/#232. | https://github.com/brianreborn/familia/pull/300 | queued | Needs Brian local-exec OK per run; check disk FS state first. Hosts were offline on 2026-11-06; LAN is back.
- Hermes Wiring (39297cdd-2fca-4a56-b02f-070b835756b0) | Reconcile
  seven local Android/guardian commits with open PR #321 without
  overwriting its eight commits (rebase onto #321 or a new draft
  branch). HVVRAM kernel defects confirmed only by static review;
  FreeBSD runtime still unverified. | https://github.com/brianreborn/familia/pull/321 | blocked on approach choice | Brian chooses rebase onto #321 vs a separate draft branch. No force push.
- Continuity (b27d49b9-86e0-42da-85a8-bc9e047235ae) | Keep #300
  Windows installer moving (draft, closes #32). sysrescue bootmgr
  repair was completed later by qodesh Worker. | https://github.com/brianreborn/familia/pull/300 | draft open | Needs PS 5.1 results and reviews.
- Senior Developer (f9fdbeaa-883a-42ab-a4d1-71efac60d295) | Track
  remaining #236 items (L13/L15/M17) and file the TR-3/TR-4 product
  issue. Daily 10 AM PT security check-in stays running (Brian said
  keep it). | https://github.com/brianreborn/familia/issues/236 | open | L15 code frozen; M17 is owner-only GitHub settings.
- Researcher (74c9df07-f048-493f-85ec-ce9ca100abe0) | Coordinate
  0.3.0 work onto main; do not start new development branches.
  Windows-only relocation remains a separate ops thread, not this
  sprint. | (coordinator) | idle since 2026-11-10 check-in relay | none for sprint coordination.
- Release Driver (8c5a35ba-0ed7-4068-9712-d651d34dfc26) | A57 chat
  model chosen 2026-11-06: LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf
  (install OK was still pending then; galaxy2 now serves LFM3).
  Help start angel's coder-angel session when llama.cpp is ready.
  | (host deploy) | partial | Brian per-host install OK if anything new is copied to a phone.
- Platform Reviewer (6f7997c0-9f0a-401f-b155-741d0e6fbfed) | Review
  the #380 follow-up docs PR (nits 1-6) and later 0.3.0 PRs against
  main. Just approved #380 and was re-reviewing #362 (now merged).
  | https://github.com/brianreborn/familia/pull/380#issuecomment-6781869353 | nits open | familia-claims repo needs Brian OK.
- Boundary Reviewer (5acb787d-4e99-4757-88bd-1c80027407c1) | File or
  review the TR-3/TR-4 product issue; review 0.3.0 PRs against main.
  Approved #362. | https://github.com/brianreborn/familia/pull/362#issuecomment-6781949185 | nits + owed issue | none.
- Race Reviewer (137401ad-19fa-4b63-9731-b9420ab02287) | #362 nits
  (Windows pytestmark, R1 fork of a threaded process). Re-review
  #169/#170 if they stay on main. | https://github.com/brianreborn/familia/pull/362#issuecomment-6781993525 | nits; #169/#170 still open | #169/#170 rebase/push was waiting on Brian; standing review-fix push OK may now cover updates.
- Fuzz Tester (4fdf3c13-4790-4414-952a-2efb2663f9e5) | #281 nexus
  localhost tmp fix 8b34e2a needs a real-user run on a disposable
  host; overlap check. Five unresolved Green-Roomz fuzz bugs remain
  (null-body hangs, Unicode/speech 500s, null mailbox crashes,
  env-path expansion). Lockdown/reboot stayed blocked (good).
  | https://github.com/brianreborn/familia/issues/281 | waiting | Needs a disposable host from Brian.
- Covert Channel Fixer (42110e92-910d-4254-838e-1077039383c8) | Next
  green-roomz fix-pack items after SSE/ESC strip (P0b constant-time
  secureEquals, P0c log/path scrubbing, P1 no cache_prompt reuse
  across tenants). familia :9931 key-fix review still listed.
  | green-roomz (no open PRs at last check) | local/unpushed as of 2026-11-06 | Brian push OK and which tree is canonical for v0.3.
- Covert Channel Reviewer (83003a65-0254-4c9d-b0e5-eb4d41c6a549) |
  Post-land re-check of 8731d03 and tool_calls name/arguments strip.
  | (review) | idle | Depends on Fixer landing the follow-up.
- Bootstraps Reviewer (0ba3d3fa-d7fb-43b1-95b9-37d137ab9651) | Review
  cbl #90/#91/#93 (L13). familia #370 is an approve in draft, not
  posted (widget unanswered); if kept, retarget #370 to main.
  | https://github.com/brianreborn/code-bootstraps-llama.cpp/pull/93 | waiting | Brian OK to post the #370 comment; #370 base is development.
- MeshForge Lead (57ccf1f0-ff2b-4192-bdd0-3b91ac0071d0) | Unpushed
  familia patches (#32 r5 into #300, and related) as of 2026-11-06;
  MeshForge research stays outside this sprint except where it
  supports familia Android thin-client shape.
  | https://github.com/brianreborn/familia/pull/300 | unpushed/check current | Push only with standing review-fix OK or a new OK.
- Other Grok Bot ASSIST (bb0c43f5-cbb1-443f-8ece-f378a7707a19) |
  Coordinate worker wakes and keep this plan current. Already
  handling the 2026-11-10 voice-call workstream.
  | this PR | in progress | none.
- code-bootstraps bot (fe440ca2-ce09-4025-96f1-342dbf9c2556) | Land
  cbl #90/#91/#93 on main (security log redaction; L13).
  | https://github.com/brianreborn/code-bootstraps-llama.cpp/pull/93 | open | reviews.
- Bootstraps Coding Evaluator (3484b2c6-d197-4a14-adca-f64c59960cd8)
  and Click-and-Go Tester (ee12012e-90da-4688-9453-2a2a557e0dfc) |
  Resume default-set coding/out-of-box tests when the 0.3.0 model
  matrix (phones + angel coder) is serving. | cbl default set | idle | models must be up; no micro-benchmark sweeps.
- Note9 Release (2e68a703-783c-45f2-bed9-95a5c9bd7eb8) | Android
  release track (#203, #321, #277 ALPHA install). | https://github.com/brianreborn/familia/issues/203 | open | #321 needs reconcile; #277 is spec-only.
- RT Scout (f0b5b48c-9591-43dc-8884-48d0b2ee4b93) | No new 0.3.0
  implementation work. Two drafted refinement comments (familia #310,
  green-roomz #44) still need Brian's yes to post. | https://github.com/brianreborn/familia/issues/310 | parked | Brian approval to post.

## 8. Open PRs still targeting familia (retarget note)

Against main (keep, do not move to development):

- #321 Android packaging (needs reconcile; see Hermes Wiring).
- #300 Windows Uninstall/Purge (draft; closes #32).
- #286 stale SPRINT.md (close after this PR merges).
- #268 routing graph UX.
- #250 L-hostloc lessons (docs; left earlier as risky).
- #249 HVVRAM design-review (draft; do not merge).
- #200 router no-op tests (draft; #199).
- #170 speculative-decoding seatbelts.
- #169 miryam coder CPU prefer + ngram opt-in.
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
- #323 FreeBSD RACCT/RCTL proposal (docs freeze if it touches FreeBSD
  docs).
- #332 Android offline handling.
- #377 X-interaction intake doc/tracker inconsistencies.
- #368 / #365 HVVRAM integration (design; do not block the release).
- Team A->B handoffs #278-283: re-audit; do not assume branches are
  current.
- cbl #90/#91/#93 as above. Older cbl Android leftovers (#13) and
  Windows parity (#11, #14, #32) may still apply.

## 10. Non-familia work found (not in this sprint)

List only. Do not wake these bots for 0.3.0 unless Brian asks.

- Posts Worker (10fcee0f-18f7-4216-9c5d-c52b075dd6b3): read-only X
  research for papers.
- Twitter Janitor (12ef3f98-4ad6-43bb-978b-3c59e773c0db): X account
  hygiene; posting still on HOLD.
- Writer (455d62af-7580-4148-b940-e92373ee27c3): writing lane.
- Paper Worker (6ab1c65a-17b4-4677-ba2c-dc8f57ef3d20): water-spinach
  paper published; linguistics paper is seed-only.
- Junior Repair A (5ec8ca8d-302e-4bfe-a3a1-5aa326744259) and B
  (86f37088-5b30-4673-9436-de8cd85cd808): Urara kindness repairs on
  HOLD.
- Kindness Protocol (9c51cd1b-c1c1-48f2-81e0-dd6d56132fc2): playbook
  only; posts need Brian OK.
- X Bug Cartographer (a24a1b8b-c3ee-4d7a-8f66-3d487959288a): X
  platform bugs.
- Hope Wave Scout (c34442d8-dabd-4fae-b7d4-bdc96b4e7c25): pass 2 of
  the Haru Urara brief not done.
- Visibility Reciprocity (cc6406c9-190e-48a5-afed-dc66e8efd268): X
  visibility research.
- Urara Epitaph (f681daec-f989-4401-b0cc-e56c2ff4206b): epitaph book.
- X research -> skill (a790aea6-4137-4a2b-8168-05181a156a24): skill
  work (group channel).
- Twitch CDN Recoverer (7d7471b8-b92a-4192-8f9a-e1eaef1ec0f5) and
  Twitch Takedown Tracer (a890371c-a67f-4e56-b011-adb5abda5292):
  electrobrains VOD forensics (read-only).
- Forensic Investigator (668ccbda-31b7-415d-857d-afc5904498c0): auth
  audit v3 PDF ready; sudo -n blocked on miryam/angel; not 0.3.0 code.
- Emergency Asylum (3c64967a-f171-4eed-b40b-cf887e018d5a): no
  assignment.
- New Bot (3d41f1d1-23e1-4b80-b040-7885d840fb6c): no assignment.
- miryam Camera Watch (e33a056a-abc2-46fb-8737-e8903153cbdf): local
  camera snapshots.
- Review Board Viewer (e38088a7-4a21-4068-9712-d651d34dfc26): curate
  /workspace/reviews (green-roomz #39 still needs Brian policy calls).
- Security Review (a35c68fe-ed46-4899-8419-6672e4236a23): group
  channel; no recent 0.3.0 claim found.
- MeshForge Lead research on NVIDIA OpenShell / office-3d stays in
  the MeshForge repo except as noted in section 7.

## 11. Sources

- Main on 2026-11-10: ROADMAP.md is still the v0.2.0 roadmap; no
  SPRINT.md and no v0.3.0 milestone existed on main. docs/HANDOFF.md
  is the 2026-10-10 resume index.
- Stale plan: PR #286 (docs/current-sprint-2026-11-02, 2026-11-02).
- Worker transcripts and 2026-11-06 local-transition checkpoints
  under /workspace/session/local-transition-2026-11-06/.
- Live GitHub issues/PRs and claims as of 2026-11-10 3:23 PM PT.
