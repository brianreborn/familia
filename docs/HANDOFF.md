# HANDOFF — 2026-10-10

Public-safe resume index after the 2026-10-10 sprint (Grok Bot credits exhausted). Label: `handoff-2026-10-10`. Private ops/SSH notes live in the private repo only.

## Landed on main (highlights)
- Pentest launch-test rule; README/PGO docs; registry records through ~53.
- Prompt-cache sizing (code-bootstraps #16) + familia pin.
- Vulkan `-ngl 0` shmem fix (`GGML_VK_VISIBLE_DEVICES=`).
- `qodesh-resident` Qwen3.5-2B selectable fallback (~0.91 t/s coarse).
- Escalation schema + hermes `--escalate` proxy (`docs/escalation.md`).

## Open issues filed this handoff
| Issue | Title |
|---|---|
| [#39](https://github.com/brianreborn/familia/issues/39) | Escalation: green-roomz, live swap, reachability/tunnel, signals |
| [#40](https://github.com/brianreborn/familia/issues/40) | Verify Vulkan ngl0 shmem fix on miryam |
| [#41](https://github.com/brianreborn/familia/issues/41) | Live-verify prompt-cache reuse (#16) |
| [#42](https://github.com/brianreborn/familia/issues/42) | Live hermes `--selftest-compaction` |
| [#43](https://github.com/brianreborn/familia/issues/43) | miryam disk swap / 4G swapfile behind zram |
| [#44](https://github.com/brianreborn/familia/issues/44) | qodesh-resident live server + GPU co-run |
| [#45](https://github.com/brianreborn/familia/issues/45) | Pre-existing test failures (closed; `test_overcommit_is_hard_error` still fails) |
| [#46](https://github.com/brianreborn/familia/issues/46) | Phones: resume phone7 + llama.cpp version match |
| [#47](https://github.com/brianreborn/familia/issues/47) | Small-model research unknowns |
| [#48](https://github.com/brianreborn/familia/issues/48) | Old-device lowram + non-AVX smoke |

## Landed since the handoff
- Model database from the full pinned HF repo; card settings as launch defaults (#51, [model-database.md](model-database.md)).
- `add-model.sh` ingests HF snapshot dirs and auxiliary models, with the role inferred.

## Already open (referenced, not duplicated)
- #29 miryam hang / RAM pressure (dropped); #38 EmbeddingGemma deferred; #32–#35 installers; #24/#25/#26 model tracks.
- Upstream code-bootstraps: #15, #14/#11, #17, #18 (see that repo).

## Offline tests
See [offline-test-plan.md](offline-test-plan.md) and `scripts/offline-test-plan.sh`. Prefer coarse binary search over dense sweeps.

## Research snapshot
[research/small-models-research.md](research/small-models-research.md) (#47).
