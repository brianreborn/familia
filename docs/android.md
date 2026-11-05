# Android: thin client to a Hermes host

Shape (Brian, 2026-11-05): **webapp first**. The phone is a thin client; a Linux or Mac
host runs Hermes (`scripts/hermes.sh --client webapp`, see [hermes-clients.md](hermes-clients.md))
and the phone browser opens that host's URL. No local model or guardian on the phone by default.

- **Smoke test (non-persistent):** `packaging/android/familia-android-smoke.sh --commit SHA --host HOST --port PORT [--https] [--url-file FILE]`.
  Shows the Llama 3.1 Community License + AUP and the Dolphin 3.0 terms (texts in
  `packaging/android/licenses/`, sha256-pinned) and needs a typed `ACCEPT` for each; `--yes` is refused.
  Host and port are validated; the one-use webapp link is read from `--url-file` and never logged.
  Everything goes in a throwaway prefix removed on exit.
- **Termux install:** `install/termux/install.sh` defaults to no local runtime. `--runtime` installs
  the cbl (`brianreborn/code-bootstraps-llama.cpp`) Android arm64 prebuilt, release
  `android-b11969-1`, sha256-checked. Which local model fits the phone's RAM: **TBD**; nothing is downloaded.
- **Office 3D:** not in this repo yet; nothing installs or stubs it.
- **Later:** a debug-signed sideload APK (a WebView shell that loads the host's webapp URL) is
  allowed. Not built yet; release-key custody is not needed for a debug build.
- Non-loopback hosts: prefer `--https` or an `ssh -L` tunnel; plain http on a LAN is warned about.
