# Android packaging (familia)

Webapp-first phone front door for Hermes. **Hermes Desktop** and the **Office 3D**
plugin do not run natively on Android (Office 3D upstream platforms: linux, macos).
The phone installs familia + the code-bootstraps-llama.cpp Android prebuilt, accepts
licenses, and serves the Hermes **webapp** to itself on 127.0.0.1 (self-hosted;
Brian 2026-11-10). Desktop + Office 3D stay on a Linux/macOS host.

## One-tap entry (ships now): Termux:Widget

1. Install Termux from F-Droid or GitHub (not Play Store).
2. Run the Termux installer once (`install/termux/install.sh` or the raw.githubusercontent.com download-then-run snippet). The widget path itself passes `--runtime cbl` when it (re)installs.
3. Symlink the widget script into Termux:Widget's shortcuts dir:

```sh
mkdir -p ~/.shortcuts
ln -sf "$HOME/familia/repo/install/termux/widget/familia-hermes-android.sh" \
       ~/.shortcuts/familia-hermes-android
```

4. Add a Termux:Widget on the home screen and tap **familia-hermes-android**.

That runs `install/termux/install-hermes-android.sh` (licenses → cbl prebuilt →
RAM-tier default model → `scripts/hermes.sh --client webapp` → `termux-open-url`).

## APK wrapper (follow-up)

A debug-signed sideload APK (license screen → Termux `RUN_COMMAND` / Custom Tab)
is the next step. This tree does **not** yet ship an APK: no Android SDK/Gradle
toolchain is assumed on the build host, and Brian OK'd the Widget path for the
sprint. Track the APK under a later PR once SDK + application id + debug
keystore are available on a build host.

## Related

- `install/termux/install.sh` — Termux install; **thin client by default** (no runtime); `--runtime cbl` (default kind) or `--runtime pkg`
- `packaging/android/familia-android-smoke.sh` — non-persistent thin-client smoke test (typed ACCEPT for Llama 3.1 + Dolphin 3.0)
- `install/termux/cbl-runtime.sh` — pin-verified download from `config/cbl-android-runtime.json` (`android-b12032-1`; b11969 opt-in fallback)
- `install/termux/phone-model-default.py` — RAM-tier default model (adjustable)
- `docs/android-hermes.md` — product shape, host Desktop/Office 3D, inconsistencies
