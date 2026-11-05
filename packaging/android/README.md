# Android packaging (familia)

Webapp-first phone front door for Hermes. **Hermes Desktop** and the **Office 3D**
plugin do not run natively on Android (Office 3D upstream platforms: linux, macos).
The phone installs familia + the code-bootstraps-llama.cpp Android prebuilt, accepts
licenses, and opens the Hermes **webapp**. Desktop + Office 3D stay on a Linux/macOS
host the phone can reach.

## One-tap entry (ships now): Termux:Widget

1. Install Termux from F-Droid or GitHub (not Play Store).
2. Run the Termux installer once (`install/termux/install.sh` or the raw.githubusercontent.com download-then-run snippet).
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

- `install/termux/install.sh` — Termux install; **default runtime = cbl prebuilt**
- `install/termux/cbl-runtime.sh` — sha256-verified download of `android-b12032-1` (fallback `android-b11969-1`)
- `install/termux/phone-model-default.py` — RAM-tier default model (adjustable)
- `docs/android-hermes.md` — product shape, host Desktop/Office 3D, inconsistencies
