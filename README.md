# FEELDZNUTTS

Your models stay on your machine. A file, a conversation, or a result moves only when you say so.

<img src="logo.png" alt="FEELDZNUTTS: Federated, Electronic, Electively-Limited, Distribution-Zoned, Neural Network, Unified, Topographical, Teleportation System" width="170">

This repository is the map. The programs live in their own checkouts, listed in `pins.txt`. Nothing here is a new model.

## Install

Two steps. Run the command, then tap through the donation notice. You do not have to pay.

Linux, macOS, and Termux:

```sh
curl -fsSL https://raw.githubusercontent.com/brianreborn/code-bootstraps-llama.cpp/main/install.sh | sh
```

Windows PowerShell:

```powershell
irm https://raw.githubusercontent.com/brianreborn/code-bootstraps-llama.cpp/main/install.ps1 | iex
```

The page opens on chat: [http://127.0.0.1:9931/?model=chat](http://127.0.0.1:9931/?model=chat). The first visit asks for the key printed in the terminal. Paste it once.

If you already have the checkout, `./start.sh` does the same job (`start.bat` on Windows). Set `INSTALL_ACK=yes` when nobody is there to tap the notice.

On a phone, run the Linux command inside Termux and keep the folder in the Termux home directory, not on shared storage.

## Settings

Change the ordinary choices without editing a script. A value you already set in the shell wins over either of these. Start the server again after you save.

The form listens on [http://127.0.0.1:9932](http://127.0.0.1:9932):

```sh
python3 scripts/panel.py
```

The same questions, in the terminal:

```sh
sh scripts/configure.sh
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\configure.ps1
```

## What you are running

You start in **chat**. That is the general model. Work that is code is handed to **coder**. **route** picks between them. **translate** is there when a language model is installed. Names such as vision, speech, and drawing wait until those files are actually on disk.

| Piece | What it is |
| --- | --- |
| [code-bootstraps-llama.cpp](https://github.com/brianreborn/code-bootstraps-llama.cpp) | The models, the server, and the installer |
| [green-roomz](https://github.com/brianreborn/green-roomz) | One name in front of one backend |
| [green-agentz](https://github.com/brianreborn/green-agentz) | The fleet |
| [green-agency](https://github.com/brianreborn/green-agency) | Retired. Not the fleet |
| [Agent-Reach](https://github.com/Panniantong/Agent-Reach) | Extra tools. Pinned in `pins.txt`, not copied here |

Linux is the system the others are measured against. A Galaxy A57 running Termux answered chat, coder, and route with the same server. The installer, the browser, and a tool call were not part of that phone run.

`/local` runs grok, agy, claude, or codex as you, on this machine. `/remote` can hand a short brief to one of those tools. It does not get your tools or your key.

When a change should be deliberate, say `begin`, then `commit`. `rollback` drops that declaration. It does not rewind the disk. If the model server you started is up, `begin` saves its memory to a file, pauses that one process only long enough to copy the file, and lets it continue.

BitTorrent, rsync, ssh, NFS, and ZFS are reserved names. The programs that would move bytes over them are not written yet.

The longer design is in `DESIGN.md`.

Code in this repository is under the Light-ware License in `LICENSE`: the 4-clause BSD license, plus an invitation to help with rent, groceries, or lights. The invitation does not bind you. The advertising line is: "This product includes software developed by Brian Fundakowski Feldman." The other checkouts keep their own licenses. llama.cpp stays MIT.

## Issues

A search of this repository does not search the others.

| Checkout | Issues |
| --- | --- |
| This map | https://github.com/brianreborn/feeldznutts/issues |
| Models, the agent, installers, the server | https://github.com/brianreborn/code-bootstraps-llama.cpp/issues |
| green-roomz | https://github.com/brianreborn/green-roomz/issues |
| green-agentz | https://github.com/brianreborn/green-agentz/issues |
| green-agency | https://github.com/brianreborn/green-agency/issues |

The license text lives in [japanglify](https://github.com/brianreborn/japanglify), which is not a product tracker. Agent-Reach issues stay on its own repository. Upstream llama.cpp issues stay on [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp/issues). This project does not patch that tree.
