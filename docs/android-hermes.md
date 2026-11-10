# Android → Hermes webapp (one-tap)

**Product shape (Brian 2026-11-05):** webapp-first on the phone. Hermes **Desktop**
and **Office 3D** run on a Linux or macOS host; the phone opens the Hermes webapp
and may later remote into that host.

## Thin client (default)

Shape (Brian, 2026-11-05): the phone is a **thin client**. A Linux or macOS host runs
Hermes (`scripts/hermes.sh --client webapp`, see [hermes-clients.md](hermes-clients.md))
and the phone browser opens that host's URL. `install/termux/install.sh` installs **no
local runtime by default**; `--runtime cbl|pkg` (or an explicit `FAMILIA_RUNTIME`) opts
in. The one-tap path below opts in with `--runtime cbl` because it serves a GGUF on the phone.

- **Smoke test (non-persistent):** `packaging/android/familia-android-smoke.sh --commit SHA --host HOST --port PORT [--https] [--url-file FILE]`.
  Shows the Llama 3.1 Community License + AUP and the Dolphin 3.0 terms (texts in
  `packaging/android/licenses/`, sha256-pinned) and needs a typed `ACCEPT` for each; `--yes` is refused.
  Host and port are validated; the one-use webapp link is read from `--url-file` and never logged.
  Everything goes in a throwaway prefix removed on exit. `--local-inference` fetches the same
  cbl prebuilt pinned in `config/cbl-android-runtime.json`, runs `llama-server --version`, removes it.
- **Termux installer license pre-gate:** before any `pkg install` or `git clone`, `install.sh`
  asks for a typed `ACCEPT` (or `--yes` / an already-accepted selection); the full
  `scripts/licenses.py gate` still runs after the clone.
- **Which host serves the webapp and how the phone reaches it** (non-loopback bind + API key,
  or an `ssh -L` tunnel) is **not decided yet**. Prefer `--https` or a tunnel; plain http on a
  LAN is warned about.
- **Later:** a debug-signed sideload APK (a WebView shell that loads the host's webapp URL).

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
   that GGUF** at that ctx (`FAMILIA_CTX`, loopback port 9941). Hermes webapp
   requires upstream `MINIMUM_CONTEXT_LENGTH` **64000** — phone tiers are
   below that, so the one-tap path **refuses Hermes clearly** (see below).
   Auth on Termux: `~/.config/familia/api.key` (same file familia-start uses).
   Adjustable via `FAMILIA_PHONE_MODEL` / `FAMILIA_PHONE_MODEL_TIER` / `FAMILIA_CTX`.
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

Phone RAM-tier ctx (2048–8192) therefore **cannot** run Hermes webapp. The
installer fails clearly instead of hanging. `familia-start` can still serve the
GGUF at the phone ctx for non-Hermes clients. For Hermes Desktop/webapp, use a
Linux/macOS host with ctx ≥ 64000 (graph `coder` uses 65536).


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
