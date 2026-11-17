# Familia v0.4.0 sprint plan

Updated: 2026-11-16 9:33 PM PT (America/Los_Angeles)

This is the current v0.4.0 sprint plan. It keeps the structure of the
v0.3.0 plan that landed in PR #400, and retargets the work.

## Status of v0.3.0

The v0.3.0 alphas stand as v0.3.0. There will be no final v0.3.0 tag.

- v0.3.0-alpha (73b876b, 2026-11-12)
- v0.3.0-alpha.1 (df0c9ce, 2026-11-12)

All remaining open v0.3.0-milestone work moved to v0.4.0 on 2026-11-16.
Count: 71 open items (70 issues and 1 open PR). Closed v0.3.0 items were
left alone, including #580 (closed completed; the draft validator from
83e7562 and 7592864 is on main but is not wired into job(), so it is
not done; see #616 and #624). The CI collection path is tracked by #605.

Moved PR: #412.

Moved issues: #29, #32, #37, #50, #70, #71, #83, #120, #150, #178, #180,
#183, #199, #203, #232, #234, #236, #277, #280, #281, #283, #293, #295,
#296, #307, #318, #323, #327, #328, #329, #330, #331, #332, #382, #383,
#384, #385, #386, #387, #388, #389, #390, #391, #392, #393, #394, #395,
#396, #397, #402, #403, #404, #406, #407, #415, #416, #418, #419, #420,
#421, #422, #475, #476, #543, #546, #551, #552, #553, #554, #555.

Milestone pages: v0.3.0 is milestone 1; v0.4.0 already existed as
milestone 2 (same naming style) and was not recreated.

## Rules

- v0.4.0 work targets main. Do not open new development-based branches
  for this sprint.
- Merges need two valid reviews of the exact PR head SHA. Signed
  reviewer comments count as reviews when they name that SHA. Only
  risky PRs go to Brian. No force push and no history rewrite.
- main is branch-protected: PRs are required (admins included), and
  force pushes are not allowed.
- HERMES_ACCEPT_LICENSES=1 stays the default.
- Swarm is paused until #608 (triage policy for the swarm draft PR
  flood) is settled. Do not start, resume, or trigger swarm workers,
  cron, or the fleet coordinator until that policy is set.
  https://github.com/brianreborn/familia/issues/608
- Platform order for this release: FreeBSD is the first reference
  platform, Android second, then Linux/macOS. Windows is last; it is
  expected to work but untested.
- Tests: use a strategic subset during work (for example
  tests/test_install*.py and other targeted files), and run one full
  clean-install validation at the end.
- Menus exit only on explicit user exit.
- No known issues ship.
- Network listeners require an API key by default. Localhost
  no-key is only for named local dev tools (see #414).
- ASCII only in this file (plain ASCII glyphs; no Unicode decoration).

## v0.4.0 target: llama.cpp v1.0.0

Per #611 (merged) and #614 (open PR against main), and
tracker #612.

- #611 docs: v0.4.0 version labels, LFM3 default honesty, and --tools
  no-waiver (must-land #630); merged as b942db4 (branch
  docs/v0.4.0-scope-alignment). Docs only; it does not
  change pins.txt or touch #604 / #605. README status becomes
  "pre-release (targeting v0.4.0)". LFM3-1.7B-Uncensored is the
  single-node default (start.sh when the host has no active topology).
  The checked-in fleet graph still uses qwen35-2b-q4km for nodes.coder
  on miryam. #611 no longer documents a --tools waiver; the
  launch-only limit is must-land #630 (no waiver).
  https://github.com/brianreborn/familia/pull/611
- #614 Pin code-bootstraps-llama.cpp to llama.cpp v1.0.0 (b12359)
  (branch cursor/repin-llama-cpp-v1.0.0-5cac). Re-pins
  code-bootstraps-llama.cpp in pins.txt from 6ab58d7 (the current pin
  on main, restored by merged PR #604) to 223bd358, the merge of
  code-bootstraps-llama.cpp PR #101 onto that repo's main. The vendor
  submodule is fork commit 2a860038, which merges official ggml-org
  llama.cpp v1.0.0 (b1b770d, build b12359) and keeps the fork patches.
  Pinned-runtime references that named b12032 are updated to b12359.
  There is no v1.0.0 Android prebuilt. #614 closes #612 once merged.
  https://github.com/brianreborn/familia/pull/614
- Until #614 lands, main stays on code-bootstraps pin 6ab58d7. Do not
  point pins.txt at b1b770d directly (that SHA is the ggml-org tag, not
  a code-bootstraps commit; see #604 and #612).

Partial revert of e9145b1 (refs #606): PR #629
(https://github.com/brianreborn/familia/pull/629), branch
revert/e9145b1-partial, head 60057a4. It deletes the six gpu-legacy
binaries, impedance_report.txt, scripts/check_design_impedance.py,
and scripts/hvvram_task.sh, and drops the later catalog rows for
those two scripts. graph.yaml is left as on main so the
llama-b11669-freebsd build line stays at b12032, matching
install/freebsd/install-familia.sh LLAMA_TAG=b12032. Brian approved
the partial revert at 9:21 PM PT on 2026-11-16. Related description
of the junk commit: #620.

## v0.4.0 must-lands (Brian, 2026-11-16 9:21 PM PT)

These must land for v0.4.0. Issue numbers below were searched on
GitHub on 2026-11-16; items without a matching issue are listed as
such and are not given a made-up number.

- Fix the launch-only --tools limit. There is no waiver; #611 now
  lists it as must-land and keeps the live argv and GET /tools check
  only as interim guidance until the fix lands. Tracking issue: #630.
  https://github.com/brianreborn/familia/issues/630
  https://github.com/brianreborn/familia/pull/611
- TR-4 fix across the #408 follow-up, #268, and graph_router.
  #621 is the must-land issue (node.role overrides a fail-closed
  model for tools and routing; graph_router.nodes_from_graph has
  the same gap). #546 is the earlier TR-3 residual / TR-4 product
  issue. #268 is the open routing-graph UX PR (node_type override).
  #408 itself is already merged (protograph skill). #621 also calls
  out a #408 follow-up (recipe graph: overriding --graph, so
  runtime.from_graph bin becomes argv[0] unchecked); no separate
  issue with that follow-up as its title was found.
  https://github.com/brianreborn/familia/issues/621
  https://github.com/brianreborn/familia/issues/546
  https://github.com/brianreborn/familia/pull/268
- start.bat must refuse --host/--port/--api-key argv overrides
  (F-6 parity with familia-start on Linux and Termux). Bind, port,
  and key come only from FAMILIA_BIND, FAMILIA_PORT, and
  FAMILIA_API_KEY_FILE (scripts/windows/start.bat:10-13, :22-23,
  :75-81). start.bat:94 already runs scripts/bind_auth_guard.py
  --ensure with --extra-start so extras cannot override bind, port,
  auth, TLS, or path (guard _is_extra_override at :56-70 and check
  at :195-203); start.bat:84-85 also clears LLAMA_API_KEY and
  LLAMA_ARG_*. Must-land #631 is to verify and test that refusal
  on Windows, and to document the env-var config. Brian confirmed
  this at 9:33 PM PT on 2026-11-16. Related context: #32, #419,
  and closed #17. The sprint-wide API-key rule is in Rules (#414).
  https://github.com/brianreborn/familia/issues/631
- A FreeBSD build and smoke test on llama.cpp b12359 (FreeBSD is
  the first reference platform). Tracking issue: #632. Related pin
  work is #612 and open PR #614. #552 (smoke-test main on primary
  Unix platforms) is the closest earlier smoke issue and is not
  specific to b12359. #614's llama.cpp pin must be a tagged or
  main-reachable commit in brianreborn/llama.cpp before the FreeBSD
  b12359 build and smoke test counts.
  https://github.com/brianreborn/familia/issues/632
  https://github.com/brianreborn/familia/issues/612
  https://github.com/brianreborn/familia/pull/614
- #616 and #624 (release-blockers): wire the 83e7562 validate_draft
  into job(), and cover the #580 gaps that #616 alone does not
  (truncation check, reject/release/backoff path, preamble and
  fence coverage). validate_draft exists on main but job() never
  calls it, so #580's protection is dead code and model drafts can
  still reach PRs unchecked. Both #616 and #624 must land before
  the swarm resumes (#608). #605 (CI collection path) remains open
  even though the path fix is already on main.
  https://github.com/brianreborn/familia/issues/616
  https://github.com/brianreborn/familia/issues/624

## Also open on v0.4.0 (filed 2026-11-16)

These are not must-lands unless listed above. They are here so they
are not lost under the "no known issues ship" rule.

- #617 hermes-escalation-config.sh execs a CWD-relative script.
  License-default is out of scope there; HERMES_ACCEPT_LICENSES=1
  stays the default (see Rules).
  https://github.com/brianreborn/familia/issues/617
- #618 generated/graph-{console,drone,security,tool-handler}.yaml
  claim tool-denial controls the schema does not implement.
  https://github.com/brianreborn/familia/issues/618
- #619 registry/models: sha256_ok re-stamped without evidence;
  local username in license path.
  https://github.com/brianreborn/familia/issues/619
- #622 gpu-legacy: Windows LoadLibraryA DLL search order; nvso
  Makefile lost the CFLAGS override.
  https://github.com/brianreborn/familia/issues/622
- #623 scripts/watchdog_test.sh never times out.
  https://github.com/brianreborn/familia/issues/623

## 1. Landed 2026-11-10 (do not redo)

- Coordinator-free pull swarm design: PR #380 merged to main at d997acd.
  https://github.com/brianreborn/familia/pull/380
- ASCII/ANSI style guide: PR #381 merged to main at 8babfd4.
  https://github.com/brianreborn/familia/pull/381
- Routing boundary tests: PR #362 went through development (merged
  there at 6ce6adf) before the main-only rule, and is now on main at
  3934b39. Residual nits and TR-3/TR-4 still open (see #546).
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

## 2. Carryover: FreeBSD 42 test failures (was a v0.3.0 blocker)

Parent: https://github.com/brianreborn/familia/issues/387
These issues are still open and now sit in the v0.4.0 milestone. Pass
condition for each remains: the test passes on angel's runner without
breaking Linux. Do not wake swarm workers to pick them up while the
swarm is paused (#608).

- #396 FIRST: host-local ~/ci/run-familia-ci.sh on angel (tee at
  lines 164-165 swallows pytest's exit status; START_HUMAN unset at
  line 455). Greens from that script are untrustworthy until this is
  fixed. The script is not in the repo. Angel's github-act-runner
  jobs run workflow steps (checkout, pytest, and similar), not this
  script (verified in Actions run 42921698653; angel-smoke.yml is
  not in this PR or on main). Status: open.
- #387 parent: FreeBSD 42 test failures. Status: open.
- #388 path resolution: familia-start refuses test key files (~15 tests).
- #389 Windows reserved names not rejected (COM/LPT superscripts,
  CONIN$/CONOUT$; 9 tests).
- #390 hermes-agent PATH shadow and /usr group-writable trust checks
  (9 tests).
- #391 missing registry/llama-builds flag tables under FAMILIA_SYNC=0.
- #392 test_bench_idle nice off-by-one (20 == 19).
- #393 hostile hop test hits HTTP 502 (related to PR #362). The
  issue now says land on main (this sprint still targets main). The
  morning pin predates #362 (a4a65b3, now on main at 3934b39).
  Re-run the test on angel at main after #362 before rewriting it.
- #394 test_hermes_upstream_compat KeyError GITHUB_TOKEN.
- #395 test_windows Activate.ps1 UTF-8 BOM on host venv.
- graph.yaml still names Nanbeige4.3-33B Q4_K_M as nanbeige-coder on
  angel, which conflicts with the no-large-models-on-FreeBSD rule
  and Brian's choice of Qwen2.5-Coder 3B 4-bit with a 0.5B draft.
  The sprint line is the intended change; fix graph.yaml in a
  separate PR. (Node-id rename work landed later in PR #610; do not
  assume this graph.yaml note is still verbatim without re-reading
  main.)
- a57-ssh-smoke.yml retarget note is from 2026-11-10; re-check the
  workflow base on main before changing it. Do not change workflows
  in this docs PR.

## 3. New product work (opened 2026-11-10; now v0.4.0)

The hot-file freeze was lifted at 3:25 PM PT on 2026-11-10. Menu,
protograph, graph.yaml, and model-picking work may proceed against
main. Do not start swarm workers while #608 is unsettled.

- #397 App catalog: virtual app store menu item; public search of open
  issues labeled applications, with a local cache. Still open; now in
  the v0.4.0 milestone.
  https://github.com/brianreborn/familia/issues/397
  Open PR #412 (draft) is the app-catalog implementation against main.
- #327-331 per-host menu redesigns (angel, galaxy1, galaxy2,
  reference). Still open; now in the v0.4.0 milestone. Code may start
  against main; keep one owner per issue so two agents do not take
  the same one.
- Completed during v0.3.0 and left on that milestone: #398 (Menu:
  intelligent model picking) and #399 (Proto model / protograph
  skill). Do not reopen them.

## 4. Transport-agnostic swarm (no extra LAN/WAN required)

Design is transport-agnostic: SMS, MMS, Wi-Fi Direct, Bluetooth, or
existing LAN should all plug into one layer. No real SMS until Brian
confirms both phones' numbers. Ask before changing Bluetooth pairing.
Claim repo brianreborn/familia-claims does not exist; creating it is
ask-first. This work is paused with the rest of the swarm until #608
is settled.

- #382 parent: transport-agnostic local coordination. Status: open,
  unclaimed. https://github.com/brianreborn/familia/issues/382
- #383 galaxy1 Wi-Fi Direct (root-free Termux/Android P2P).
  Status as of 2026-11-10: claimed:galaxy1.
  https://github.com/brianreborn/familia/issues/383
- #384 galaxy2 SMS/MMS (termux-api, limits, signed envelopes).
  Status as of 2026-11-10: claimed:galaxy2.
  https://github.com/brianreborn/familia/issues/384
- #385 miryam Bluetooth (BlueZ RFCOMM/BLE GATT to phones).
  Status as of 2026-11-10: claimed:miryam.
  https://github.com/brianreborn/familia/issues/385
- #386 angel transport abstraction + LAN baseline (lossy-link leases,
  BT dongle). Status as of 2026-11-10: claimed:angel.
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
  need that merge (against main). Re-check before acting; this line
  is from 2026-11-10.
- Angel coder is not serving yet. Start in screen session coder-angel
  once a working FreeBSD llama.cpp server exists. Do not restart an
  already-running server; do not touch the NTFS disk.
- #183 TOP PRIORITY: performance-test all models on real suites
  (HumanEval, MBPP, MMLU, tokens/s) plus deployment topology.
  Charts/PR intended in familia-private under bench/2026-11-10/.
  In progress on miryam (screen bench-report) as of 2026-11-10, low
  priority.

## 6. Security and review follow-ups

Tracker: https://github.com/brianreborn/familia/issues/236

- L13: tmp-file issue; open until code-bootstraps-llama.cpp #93 merges.
  https://github.com/brianreborn/code-bootstraps-llama.cpp/pull/93
- L14: node keys over plain HTTP; startup warning landed in #374.
- L15: ui_bridge.py printed unstripped control characters (same
  class as #303). Fixed by #547 (merged to main at f49e3be on
  2026-11-11; ui_bridge sanitizes server strings and gates ANSI
  on TTY). Status: landed.
  https://github.com/brianreborn/familia/pull/547
- M17 (Medium, extends M6): miryam self-hosted runner reachability
  to the A57s via the #367 dispatcher key. Owner-only GitHub
  settings; details in #236, not in this public file.
  https://github.com/brianreborn/familia/issues/236#issuecomment-6774972991
  M17 status: see #236.
  Self-hosted workflows merging to main are gated on M17 settings first.
- TR-3 residual and TR-4 role-override gap are now filed as #546
  (moved to v0.4.0 with the other open items).
- #362 nits (non-blocking): POSIX skipif in test_race_routing.py
  should be scoped to the fork test only; Windows pytestmark skips
  the whole race file; R1 fork()s a threaded process. #362 itself
  went through development before the main-only rule.

## 7. Worker line items (snapshot from 2026-11-10)

Format: owner | work | link | status | blocker

These lines are the 2026-11-10 worker sweep. They are not a wakeup
list. Swarm stays paused until #608 is settled.

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
- Senior Developer | Track remaining #236 items (L13/M17; L15
  landed in #547) and file the TR-3/TR-4 product issue (Boundary
  Reviewer reviews it). Daily 10 AM PT security check-in stays
  running (Brian said keep it). | https://github.com/brianreborn/familia/issues/236 | open | L15 landed in #547; M17 is owner-only GitHub settings. #546 now exists for TR-3/TR-4.
- Researcher | Coordinate 0.4.0 work onto main; do not start new
  development branches. Windows-only relocation remains a separate
  ops thread, not this sprint. | (coordinator) | idle since 2026-11-10 check-in relay | swarm paused until #608.
- Release Driver | A57 chat model chosen 2026-11-06:
  LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf (install OK was still pending
  then; galaxy2 now serves LFM3). Help start angel's coder-angel
  session when llama.cpp is ready. | (host deploy) | partial | Brian per-host install OK if anything new is copied to a phone.
- Platform Reviewer | Review the #380 follow-up docs PR (nits 1-6)
  and later PRs against main. Just approved #380 and was
  re-reviewing #362 (now merged). | https://github.com/brianreborn/familia/pull/380#issuecomment-6781869353 | nits open | familia-claims repo needs Brian OK.
- Boundary Reviewer | Review the TR-3/TR-4 product issue (now #546);
  review PRs against main. Approved #362. | https://github.com/brianreborn/familia/pull/362#issuecomment-6781949185 | nits | none.
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
  | green-roomz (no open PRs at last check) | local/unpushed as of 2026-11-06 | Brian push OK and which tree is canonical.
- Covert Channel Reviewer | Post-land re-check of 8731d03 and
  tool_calls name/arguments strip. | (review) | idle | Depends on Fixer landing the follow-up.
- Bootstraps Reviewer | Review cbl #90/#91/#93 (L13). familia #370
  later merged to main (Declare PyYAML and pytest as dev test deps).
  | https://github.com/brianreborn/code-bootstraps-llama.cpp/pull/93 | waiting | re-check cbl PR state before review.
- MeshForge Lead | Unpushed familia patches (#32 r5 into #300, and
  related) as of 2026-11-06; MeshForge research stays outside this
  sprint except where it supports familia Android thin-client
  shape.
  | https://github.com/brianreborn/familia/pull/300 | unpushed/check current | Push only with standing review-fix OK or a new OK.
- Other Grok Bot ASSIST | Coordinate worker wakes and keep this
  plan current. Already handling the 2026-11-10 voice-call
  workstream. | this PR | paused with the swarm until #608 | none.
- code-bootstraps bot | Land cbl #90/#91/#93 on main (security log
  redaction; L13).
  | https://github.com/brianreborn/code-bootstraps-llama.cpp/pull/93 | open as of 2026-11-10 | reviews.
- Bootstraps Coding Evaluator and Click-and-Go Tester | Resume
  default-set coding/out-of-box tests when the model matrix
  (phones + angel coder) is serving. | cbl default set | idle | models must be up; no micro-benchmark sweeps.
- Note9 Release | Android release track (#203, #321, #277 ALPHA
  install). | https://github.com/brianreborn/familia/issues/203 | open | #321 needs reconcile; #277 is spec-only.
- RT Scout | No new implementation work while the swarm is paused.
  Two drafted refinement comments (familia #310, green-roomz #44)
  still need Brian's yes to post. | https://github.com/brianreborn/familia/issues/310 | parked | Brian approval to post.

## 8. Open PRs still targeting familia (retarget note)

Checked 2026-11-16 against GitHub, plus PRs opened later that day.
Against main (keep, do not move to development):

- #629 partial revert of e9145b1 (open; keep graph.yaml at b12032;
  refs #606).
- #615 this sprint-doc PR (open).
- #614 llama.cpp v1.0.0 pin (open; see the target section above).
- #611 v0.4.0 docs alignment (open; docs only; --tools waiver is
  not accepted, see must-lands).
- #412 App catalog (draft; #397).
- #321 Android packaging (needs reconcile; see Hermes Wiring).
- #300 Windows Uninstall/Purge (draft; closes #32).
- #268 routing graph UX.
- #250 L-hostloc lessons (docs; left earlier as risky).
- #249 HVVRAM design-review (draft; do not merge).
- #200 router no-op tests (draft; #199).
- #170 speculative-decoding seatbelts. Update by merging main in
  (no rebase and no force push).
- #169 miryam coder CPU prefer + ngram opt-in. Update by merging
  main in (no rebase and no force push).
- #165 #164 #163 drafts (Terminal-RSI, monitor, Jev).

Closed or merged since the 2026-11-10 list (do not reopen):

- #286 stale SPRINT.md: closed (the v0.3.0 plan landed via #400).
- #370 PyYAML/pytest dev deps: merged to main.
- #363 hermes userinfo scrub: merged to main.
- #166 Harness2 design scaffolding: merged to main.

## 9. Carryover still open from the 2026-11-02 list

These stayed open and remain in scope if they affect v0.4.0. Many
handoff items (#277-283) may be stale relative to later merges;
re-check before starting. Most of these now sit in the v0.4.0
milestone.

- #203 bulletproof small-device deployment (epic).
- #277 ALPHA unattended install / license gate (spec only; new branch
  from main).
- #32 / #300 Windows installer.
- #234 Windows/pwsh tests skipped on Linux.
- #232 start.sh --yes screen timeout (still open; now in v0.4.0).
  #227 familia-menu.sh --pipe hang was closed completed and left on
  v0.3.0.
- #199 router no-op R&D (#200 draft).
- #293 install.sh has no published SHA256SUMS.
- #295 OOM-killer relax / soft limits; #307 miryam LFM3 thread tuning.
- #323 FreeBSD RACCT/RCTL proposal (docs freeze lifted; work against
  main if it touches FreeBSD docs).
- #332 Android offline handling.
- #377 X-interaction intake doc/tracker inconsistencies (already in
  v0.4.0).
- #365 HVVRAM driver progress remains open in v0.4.0. #368 is already
  closed; leave it alone.
- Team A->B handoffs still open in v0.4.0: #277, #280, #281, #283.
  Already closed (leave them alone): #278, #279, #282. Re-audit
  before starting; do not assume branches are current.
- cbl #90/#91/#93 as above. Older cbl Android leftovers (#13) and
  Windows parity (#11, #14, #32) may still apply.

## 10. Non-familia work found (not in this sprint)

List only. Do not wake these bots for v0.4.0 unless Brian asks.
The 2026-11-10 assignments are left as recorded.

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
  miryam/angel; not v0.4.0 code.
- Emergency Asylum: no assignment.
- New Bot: no assignment.
- miryam Camera Watch: local camera snapshots.
- Review Board Viewer: curate /workspace/reviews (green-roomz #39
  still needs Brian policy calls).
- Security Review: group channel; no recent 0.3.0 claim found.
- MeshForge Lead research on NVIDIA OpenShell / office-3d stays in
  the MeshForge repo except as noted in section 7.

## 11. Sources

- This update (2026-11-16 9:33 PM PT): Race review of PR #615 at
  66cd77e (https://github.com/brianreborn/familia/pull/615#pullrequestreview-5933451733)
  and Boundary comment
  https://github.com/brianreborn/familia/pull/615#issuecomment-6939558429.
  B2: #614 pin must be tagged or main-reachable before the FreeBSD
  b12359 smoke counts (#632). B3: #624 is a release-blocker with
  #616, both required before swarm resumes (#608). #580 is not
  done (validator unwired; #616/#624). L15 landed in #547
  (f49e3be). B1 resolved by Brian at 9:33 PM PT: start.bat must
  refuse argv overrides; #631 rescoped to verify the existing
  F-6 guard and document FAMILIA_BIND / FAMILIA_PORT /
  FAMILIA_API_KEY_FILE. Rules now include menus-exit-only, no
  known issues ship, and API key on network listeners. Also
  listed: #617, #618, #619, #622, #623.
- Prior update (2026-11-16 9:29 PM PT): filed tracking issues #630
  (--tools persist, no waiver), #631 (start.bat overrides), and
  #632 (FreeBSD b12359 smoke) on milestone v0.4.0 with the
  must-land label.
- Prior update (2026-11-16 9:26 PM PT): Brian's v0.4.0 must-lands
  (9:21 PM PT); PR #629 partial revert of e9145b1; issue/PR reads
  of #17, #32, #408, #419, #546, #552, #580, #605, #606, #611,
  #612, #614, #616, #620, #621, #624, and #629. A standalone #408
  follow-up issue was still not found.
- Earlier this evening (2026-11-16 8:46 PM PT): GitHub milestones 1
  (v0.3.0) and 2 (v0.4.0); tags v0.3.0-alpha and v0.3.0-alpha.1;
  origin/main at 26d9720; issue/PR reads of #580, #604, #605, #606,
  #608, #611, #612, and #614; PR state checks for #163-#170, #200,
  #249, #250, #268, #286, #300, #321, #363, #370, #412.
- Prior plan on main: PR #400 (docs: v0.3.0 sprint plan from the
  2026-11-10 worker sweep).
- Stale earlier plan: PR #286 (docs/current-sprint-2026-11-02),
  later closed.
- Worker transcripts and 2026-11-06 local-transition checkpoints
  under /workspace/session/local-transition-2026-11-06/.
- Review fixes from Race, Boundary, and Platform on PR #400
  (comments 6782152898, 6782156531, 6782249291, 6782251389,
  and 6782273617).
