# Phone system agents (Bixby, Gemini)

familia can use the assistant that ships on a phone (Gemini on Android, Bixby on Samsung)
next to the Termux llama.cpp nodes. It's **off by default** and **needs no root**: it goes
through [Shizuku](https://github.com/RikkaApps/Shizuku), which gives ADB-shell rights over
wireless debugging. Why no root, with sources: [research/phone-system-agents.md](research/phone-system-agents.md) (#80).

**Status: not tested on a real phone yet.** Everything below was checked against a mock
`rish` in `tests/test_system_agents.py`. Reading Gemini's reply off the screen is a heuristic
until a live test confirms the UI labels.

## What works, and what does not

| Provider / backend | Where it runs | familia command | State |
|---|---|---|---|
| `gemini` / `app` | **cloud** (Google, your Google account) | `ask`, `open` | wired; live test pending |
| `gemini` / `nano` | on-device (AICore) | – | **not available**: needs a companion Android app built on ML Kit GenAI; familia ships none. 2024+ flagships only, bootloader locked |
| `bixby` / `app` | **cloud** (Samsung; Perplexity for web answers) | `open` only | `ask` not wired: Samsung documents no text entry |

## Set up on the phone (once)

You do these steps on the phone yourself. familia installs nothing.

1. Get Shizuku from its GitHub releases or the IzzyOnDroid F-Droid repo (both listed at
   <https://shizuku.rikka.app/download/>). License: Apache-2.0.
2. Start it:
   * Android 11+: Developer options → Wireless debugging, then pair once from Shizuku.
   * Android 10 and older: run `adb shell sh /sdcard/Android/data/moe.shizuku.privileged.api/start.sh`
     from a computer.
3. In Shizuku, open "Use Shizuku in terminal apps" and export `rish` and `rish_shizuku.dex`.
   Copy both into Termux's home directory (`~`), not `/sdcard`, because Android 14+ refuses a
   writable dex. Then `chmod +x ~/rish`.
4. Check it with `python3 scripts/termux/system_agent.py probe`. It should say `shizuku: running (uid 2000)`.

**After every reboot Shizuku is stopped** (that's how Android works without root). `probe`
then reports `stopped-after-reboot`, and `familia-monitor` shows
`assistants: shizuku STOPPED after reboot`. Open Shizuku and press Start. It isn't a crash and
no death alert is raised.

## Turn one on (graph.yaml)

```yaml
system_agents:
  gemini-phone:
    kind: system-agent
    provider: gemini        # gemini | bixby
    backend: app            # app (cloud) | nano (on-device; gemini only)
    host: <a phone host>    # must be kind: phone
    transport: shizuku
    cloud: true             # must match the backend: app = true, nano = false
    consent: ask            # the only value: every cloud call needs consent
    status: planned         # off | planned | active
    experimental: true
    agents: [hermes]        # optional: agents allowed to use it; never one a pentest uses
```

`validate_graph.py` checks this: the host is a phone, `cloud` matches the backend, bixby has
no nano backend, and no pentest's agent or `tools` names a system agent. `licenses.py review`
lists Shizuku and the provider's service terms once an entry is `planned` or `active`.

## Commands (on the phone, in Termux)

| Command | Does |
|---|---|
| `system_agent.py probe [--json]` | Shizuku state + installed assistants; writes `~/.cache/familia/system-agent.json` for the monitor |
| `system_agent.py consent --provider gemini --grant / --revoke / --show` | standing consent for cloud calls (`~/.config/familia/system-agent-consent.json`) |
| `system_agent.py open --provider gemini\|bixby` | bring the app to the front (sends nothing) |
| `system_agent.py ask --provider gemini --text "..." [--json] [--dry-run] [--yes-cloud]` | send the text to Gemini, press Send, read the reply off the screen |

`ask` without consent asks on a terminal and refuses (exit 3) otherwise. `--dry-run` prints
the exact `rish` commands and sends nothing. The phone must be unlocked. The UI dump file is
deleted right after each read. With `FAMILIA_ROLE=pentest`, every command is refused.

The same commands are in the menu under Hosts and in the CLI (`familia phone agent probe`,
`familia phone agent ask ...`, `familia phone agents`).

## Pending

* A live test on phone7/phone8 needs your OK and a phone in range. Check each phone first:
  run `getprop ro.build.version.release` (Shizuku without a PC needs Android 11+; the
  Gemini app needs 10+ and ≥2 GB RAM).
* Mapping Bixby's UI for `ask`.
* A Gemini Nano companion app is only an idea. Nothing exists, and nothing gets built without
  review.
