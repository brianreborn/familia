# Android → Hermes webapp (one-tap)

**Product shape (Brian 2026-11-05):** webapp-first on the phone. Hermes **Desktop**
and **Office 3D** run on a Linux or macOS host; the phone opens the Hermes webapp
and may later remote into that host.

## What you get on the phone

1. Termux:Widget (or `install/termux/install-hermes-android.sh`) one-tap entry.
2. License gate via `scripts/licenses.py`, including **Dolphin3** and **Llama 3.1**
   Community License terms at minimum (`--add-model` + `--require-llama31`).
3. Runtime = **code-bootstraps-llama.cpp** Android arm64 prebuilt by default
   (`android-b12032-1`, falling back to `android-b11969-1` until b12032 is
   published). Download to a named file, verify sha256 against `SHA256SUMS`
   (and the GitHub API digest when present). Never pipe a download into a shell.
4. Default GGUF chosen by **usable RAM** (`total - reserve_ram_mib`); see
   `install/termux/phone-model-default.py --list-tiers`. Adjustable via
   `FAMILIA_PHONE_MODEL` / `FAMILIA_PHONE_MODEL_TIER`.
5. `scripts/hermes.sh --client webapp` and `termux-open-url` on the one-use link.

Opt into Termux's `llama-cpp` package instead with `FAMILIA_RUNTIME=pkg` or
`install/termux/install.sh --runtime pkg`.

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
| Termux runtime | `install/termux/install.sh` header and `docs/install.md` said Termux `llama-cpp` pkg is the runtime | Default is now **cbl prebuilt**; pkg is `--runtime pkg` / `FAMILIA_RUNTIME=pkg` |
| Click-and-go on phones | Some docs implied a finished APK / click path | Shipping path is **Termux:Widget** + scripts; APK is a documented follow-up (`packaging/android/README.md`) |
| Android release pin | Release notes / mental model may still cite only b11969 | Installer prefers **android-b12032-1**, falls back to **android-b11969-1** when b12032 is missing |
| Hermes Desktop on Android | Sprint goal named Desktop + Office 3D on Android | **Not native**; webapp on phone, Desktop/Office 3D on Linux/macOS host |

## Related

- `install/termux/install.sh`, `cbl-runtime.sh`, `install-hermes-android.sh`
- `packaging/android/README.md` (Widget now, APK later)
- `docs/hermes-clients.md`, `docs/licenses.md`, `docs/ram-safety.md`
