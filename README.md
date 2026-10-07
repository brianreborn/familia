# FEELDZNUTTS

Federated Electronic Electively-Limited Distribution-Zoned Neural Network Unified Topographical Teleportation System.

This repository is the graph. The projects it composes stay in their own checkouts. Their source is not copied here, and their licenses are not changed. Code written in this repository is under the Light-ware License in `LICENSE` (4-clause BSD plus a non-binding invitation). The advertising line is: "This product includes software developed by Brian Fundakowski Feldman."

`DESIGN.md` is the accepted design. `pins.txt` records the checkouts and the revisions that were current when this repository was created.

## Where the issues are

Searching this repository does not search the others. Each checkout has its own tracker:

| Checkout | Issues |
| --- | --- |
| This graph | https://github.com/brianreborn/feeldznutts/issues |
| `code-bootstraps-llama.cpp` (models, the agent, installers, serve) | https://github.com/brianreborn/code-bootstraps-llama.cpp/issues |
| `green-roomz` (alias gateway) | https://github.com/brianreborn/green-roomz/issues |
| `green-agentz` (fleet, green-zkillz) | https://github.com/brianreborn/green-agentz/issues |
| `green-agency` (retired; do not treat it as the fleet) | https://github.com/brianreborn/green-agency/issues |

`japanglify` is the Light-ware license text, not a product tracker: https://github.com/brianreborn/japanglify . Agent-Reach issues stay on https://github.com/Panniantong/Agent-Reach/issues . Upstream llama.cpp issues stay on https://github.com/ggml-org/llama.cpp/issues . This tree does not patch that checkout.

The llama.cpp checkout at the pin above opens the UI on `chat`. The preset aliases are `chat` for general, `route` for decision, and `translate` for language. The installer copies the tree and asks for the donation notice (`INSTALL_ACK=yes` for a non-interactive run). `/local` runs `grok`, `agy`, `claude`, or `codex` as the user. `begin`, `commit`, `rollback`, and `status` on `/local` or `/remote` share `tx.json`. A nested begin is a savepoint. `begin` names a snap directory. A declared write copies the file's bytes into that snap first. When a llama-server this user started is listening, `begin` also saves its slot dumps, stops that pid only long enough to copy the closed files, and continues it. Agent-Reach is pinned in `pins.txt` and is not copied into this tree. `SIGSTOP` is sent only to pids this user owns. ZFS and btrfs are not invoked unless `FEELD_SNAP_FS` names one that is installed. BitTorrent, trackers, rsync, ssh, NFS, and ZFS send are still names only. `/local` exists; the protocol code does not.

Android has a live Termux run on a Galaxy A57 (SM-A576U). `serve.sh` there answered `chat`, `coder`, and `route`. `start.sh` itself, a tool call, the UI, Vulkan, and the installer were not run on that phone. The leftovers are filed on the llama.cpp checkout, and the platform issue in this repo stays open.
