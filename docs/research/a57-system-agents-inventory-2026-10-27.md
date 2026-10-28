# A57 system-agent inventory (live, read-only) — 2026-10-27

Phone path for [#80](https://github.com/brianreborn/familia/issues/80). Branch: `swarm/qodesh/system-agents-80`.

**Scope:** package / OS presence only via Termux SSH. No Shizuku install, no UI automation, no cloud `ask`.

## galaxy2 (reachable)

| Field | Value |
|-------|-------|
| Model | SM-A576U |
| Android / SDK | 17 / 37 |
| Manufacturer | samsung |
| Bixby agent | present (`com.samsung.android.bixby.agent`) |
| Bixby wakeup | present |
| Gemini app (bard) | present (`com.google.android.apps.bard`) |
| Google app | present (`com.google.android.googlequicksearchbox`) |
| AICore (`com.google.android.as`) | present |
| Shizuku (`moe.shizuku.privileged.api`) | **not installed** |
| `rish` in Termux | **missing** |

Green-Roomz on this handset was already healthy earlier the same day (`:18081` tool-router ready).

## galaxy1

SSH banner timed out from miryam at inventory time (same LAN-drop / process-lifetime track Platform noted). No package inventory this pass.

## Blockers for Phase-2 live probe

1. Shizuku must be installed from a user-allowed source ([download](https://shizuku.rikka.app/download/)) and started (post-reboot again).
2. Operator OK before any non-dry-run `system_agent.py open|ask`.
3. `scripts/termux/system_agent.py` needs to be on-device (or run from a synced familia tree).

## Next on this branch

- [ ] Re-check galaxy1 when SSH returns
- [ ] After Shizuku install OK: `system_agent.py probe --dry-run` then live `probe`
- [ ] Map Bixby UI for text entry (still undocumented)
- [ ] Confirm Gemini Send / reply heuristics on SM-A576U
