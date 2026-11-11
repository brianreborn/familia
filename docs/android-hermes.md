# Android → Hermes webapp (one-tap)

**Product shape (Brian 2026-11-10, "self-hosting"):** the phone serves its own
Hermes **webapp**, bound to **127.0.0.1** only. Hermes **Desktop** and
**Office 3D** still run on a Linux or macOS host (not native on Android).

## Thin client (default)

Shape (Brian, 2026-11-10): **self-hosted**. The phone runs Hermes
(`scripts/hermes.sh --client webapp`, see [hermes-clients.md](hermes-clients.md))
and serves that webapp to itself on **127.0.0.1**. No outside host is required
for the webapp. `install/termux/install-hermes-android.sh` (the one-tap path)
opts in to a local runtime with `--runtime cbl` and starts `familia-start` on
loopback port 9941. `install/termux/install.sh` alone still installs **no**
local runtime unless you pass `--runtime cbl|pkg` (or set `FAMILIA_RUNTIME`).

- **Bind and API key:** default bind is `127.0.0.1`. The installer requires an
  API key file even on loopback (mode 0600, under Termux `$HOME`, not shared
  storage), because other Termux apps and adb can reach `127.0.0.1` on a phone;
  any non-loopback bind always requires it. Plain http on a LAN is warned about; prefer `--https` or an
  `ssh -L` tunnel if you ever expose the webapp off-box.
- **Smoke test (non-persistent):** `packaging/android/familia-android-smoke.sh --commit SHA --host HOST --port PORT [--https] [--url-file FILE]`.
  Shows the Llama 3.1 Community License + AUP and the Dolphin 3.0 terms (texts in
  `packaging/android/licenses/`, sha256-pinned) and needs a typed `ACCEPT` for each; `--yes` is refused.
  Host and port are validated; the one-use webapp link is read from `--url-file` and never logged.
  Everything goes in a throwaway prefix removed on exit. `--local-inference` fetches the same
  cbl prebuilt pinned in `config/cbl-android-runtime.json`, runs `llama-server --version`, removes it.
  Point `--host` at `127.0.0.1` for the self-hosted path, or at another host to try a remote webapp.
- **Termux installer license pre-gate:** before any `pkg install` or `git clone`, `install.sh`
  asks for a typed `ACCEPT` (or `--yes` / an already-accepted selection); the full
  `scripts/licenses.py gate` still runs after the clone. Widget taps never pass `--yes`.
- **Later:** a debug-signed sideload APK (a WebView shell that loads the phone's
  loopback webapp URL).

## One-tap local path (opt-in runtime)

1. Termux:Widget (or `install/termux/install-hermes-android.sh`) one-tap entry.
2. License gate via `scripts/licenses.py` for the **selected model** (e.g. LFM3
   on an A57) **plus Dolphin3** and **Llama 3.1** Community License terms
   (`--add-model` ×2 + `--require-llama31`).
3. Runtime = **code-bootstraps-llama.cpp** Android arm64 prebuilt by default.
   Pin is `config/cbl-android-runtime.json` (**android-b12032-1** + its tarball
   sha256). Verify **only** against that pin. Older **android-b11969-1** is an
   explicit opt-in fallback (`FAMILIA_CBL_ANDROID_TAG` + `FAMILIA_CBL_ANDROID_SHA256`;
   see `fallback_opt_in` in the pin file). Download to a named file; never pipe a
   download into a shell. Offline re-runs reuse a previously verified unpack.
   `FAMILIA_CBL_REPO`/`API`/`DOWNLOAD_URL`/`PIN_FILE` overrides are refused
   unless an explicit `FAMILIA_CBL_ANDROID_SHA256` (+ TAG) is also given
   (loud warning when allowed).
4. Default GGUF + **context** chosen by **usable RAM** (`total -
   reserve_ram_mib`, negative usable clamped to 0); see
   `install/termux/phone-model-default.py --list-tiers`:

   | usable MiB | tier   | model                         | ctx  |
   |------------|--------|-------------------------------|------|
   | < 1024     | tiny   | `smollm2-135m-q4-phone`       | 2048 |
   | < 2048     | small  | `qwen25-05b-q4km-phone`       | 2048 |
   | < 4096     | medium | `lfm3-17b-uncensored-q4km`    | 4096 |
   | ≥ 4096     | large  | `dolphin3-cyber-8b-q2k`       | 8192 |

   The chosen `.gguf` is downloaded with its graph sha256 pin
   (`install/termux/fetch-phone-model.py`). **`familia-start` loads and serves
   that GGUF** on loopback port 9941. Hermes webapp requires upstream
   `MINIMUM_CONTEXT_LENGTH` **64000**. The one-tap path does **not** use the
   tier chat ctx for Hermes: if `FAMILIA_CTX` is unset, it is raised to
   **65536** (#125) and the server is started with **q8_0 KV** and **-np 1**
   (#203 / REQUIREMENTS.md). A phone is admitted when usable RAM
   (`MemTotal - reserve 5120`) meets the 64k floor (default
   `FAMILIA_MIN_USABLE_MIB=2048`, measured galaxy2 LFM3 RSS; #548). An
   explicit `FAMILIA_CTX` below 64000 is still refused; do not lower
   `min_ctx`. Auth on Termux: `~/.config/familia/api.key` (same file
   familia-start uses). Adjustable via `FAMILIA_PHONE_MODEL` /
   `FAMILIA_PHONE_MODEL_TIER` / `FAMILIA_CTX` / `FAMILIA_RAM_MIB` /
   `FAMILIA_MIN_USABLE_MIB`.
5. `familia-start` then `bash scripts/hermes.sh --client webapp`, and
   `termux-open-url` on the URL from hermes output / a readiness poll (no sleep
   + guessed port). A second tap reuses 9941 when it already serves the expected
   model, otherwise restarts it; readiness wait scales with GGUF size (up to a
   few minutes). Widget taps launch only, never pass `--yes`, and clear
   inherited `INSTALL_ACK` / `FAMILIA_ACCEPT_LICENSES` /
   `FAMILIA_ACCEPT_UNKNOWN_LICENSES` / `FAMILIA_LICENSE_ACCEPT_FILE`.

Opt into Termux's `llama-cpp` package instead with `FAMILIA_RUNTIME=pkg` or
`install/termux/install.sh --runtime pkg`.

## Hermes-agent 64K floor (phones)

Upstream **hermes-agent** sets `MINIMUM_CONTEXT_LENGTH = 64_000` in
`agent/model_metadata.py` and rejects smaller windows at agent init for
custom/llama.cpp providers (`agent/agent_init.py`). Maintainer guidance
(NousResearch/hermes-agent#11096, #8430): `model.context_length` cannot lower
that floor; the closed `HERMES_MIN_CONTEXT_LENGTH` env PR is not upstream.
LM Studio has a provider-specific exception — not used on Termux.
Do **not** lower `agents.hermes.min_ctx` (Brian, #125).

Phone RAM-tier *chat* ctx is still 2048–8192 (non-Hermes `familia-start`
defaults). The Hermes one-tap path applies the in-tree workarounds instead of
refusing every phone:

1. **Raise ctx to 65536** when `FAMILIA_CTX` is unset — the same window as
   graph `coder` / `angel-coder` (#125 / #127). An explicit `FAMILIA_CTX`
   below 64000 is still refused, clearly, before any license or install work.
2. **Quantized KV + one slot:** `familia-start` passes `-ctk q8_0 -ctv q8_0
   -np 1` (REQUIREMENTS.md, #203) so 64K can fit under `reserve_ram_mib: 5120`
   without lowering the reserve or assuming phone swap (Android stays strict
   in [ram-safety.md](ram-safety.md)).
3. **Usable-RAM admit:** `MemTotal - 5120` must be at least
   `FAMILIA_MIN_USABLE_MIB` (default **2048** MiB) at ctx 64000, scaled
   linearly for other windows. The 2048 figure is the measured galaxy2
   LFM3-1.7B RSS at 64k (#548). A typical ~7.4–8 GiB phone (usable ~2480
   MiB) passes; a phone whose usable RAM is 0 after reserve is refused
   with a RAM message, not a fake "ctx too small" message.

`familia-start` can still serve the GGUF at a smaller ctx for non-Hermes
clients when the Hermes path is not used. Hermes Desktop / Office 3D stay
on a Linux/macOS host.


## Host: Hermes Desktop + Office 3D

On a Linux or macOS machine with Hermes Desktop ≥ 0.20.0:

```sh
hermes plugins install office-3d
hermes plugins enable office-3d
# then launch Desktop through familia when the graph is wired:
scripts/hermes.sh --client desktop --yes
```

Office 3D's upstream manifest lists `platforms: [linux, macos]` only — not
Android. The phone stays on webapp chat unless you add a remote-Desktop path.

## RAM-tier defaults (policy, adjustable)

| usable MiB (`total - reserve`) | tier   | default model              |
|--------------------------------|--------|----------------------------|
| < 1024                         | tiny   | `smollm2-135m-q4-phone`    |
| < 2048                         | small  | `qwen25-05b-q4km-phone`    |
| < 4096                         | medium | `lfm3-17b-uncensored-q4km` |
| ≥ 4096                         | large  | `dolphin3-cyber-8b-q2k`    |

Default `reserve_ram_mib` on phones is **5120** (`FAMILIA_RESERVE_MIB`). A ~7.4 GiB
phone therefore lands in **medium**. Dolphin3 Q2_K (~3 GiB) needs the large tier
(or a lower reserve) and acceptance of Dolphin3 + Llama 3.1 licenses.

## Docs vs code (follow the code)

| Topic | Docs that said | Code that wins |
|---|---|---|
| Termux runtime | `install/termux/install.sh` header and `docs/install.md` said Termux `llama-cpp` pkg is the runtime | Default is **no local runtime** (thin client). `--runtime cbl` = cbl prebuilt (default kind); `--runtime pkg` / `FAMILIA_RUNTIME=pkg` = Termux `llama-cpp` |
| Click-and-go on phones | Some docs implied a finished APK / click path | Shipping path is **Termux:Widget** + scripts; APK is a documented follow-up (`packaging/android/README.md`) |
| Android release pin | Mental model may still cite b11969 only | Pin file **`config/cbl-android-runtime.json`** is authoritative (**android-b12032-1**); b11969-1 is explicit opt-in fallback |
| Hermes Desktop on Android | Sprint goal named Desktop + Office 3D on Android | **Not native**; webapp on phone, Desktop/Office 3D on Linux/macOS host |

## Related

- `config/cbl-android-runtime.json`, `install/termux/{install,cbl-runtime,install-hermes-android,fetch-phone-model}.*`
- `packaging/android/README.md` (Widget now, APK later)
- `docs/hermes-clients.md`, `docs/licenses.md`, `docs/ram-safety.md`
