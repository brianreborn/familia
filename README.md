# FEELDZNUTTS

Federated Electronic Electively-Limited Distribution-Zoned Neural Network Unified Topographical Teleportation System.

This repository is the graph. The projects it composes stay in their own checkouts. Their source is not copied here, and their licenses are not changed. Code written in this repository is under the Light-ware License in `LICENSE` (4-clause BSD plus a non-binding invitation). The advertising line is: "This product includes software developed by Brian Fundakowski Feldman."

`DESIGN.md` is the accepted design. `pins.txt` records the checkouts and the revisions that were current when this repository was created.

The llama.cpp checkout at the pin above opens the UI on `chat`. The preset aliases are `chat` for general, `route` for decision, and `translate` for language. The installer copies the tree and asks for the donation notice (`INSTALL_ACK=yes` for a non-interactive run). `/local` runs `grok`, `agy`, `claude`, or `codex` as the user. `begin`, `commit`, `rollback`, and `status` on `/local` or `/remote` share `tx.json`. A nested begin is a savepoint. `begin` names a snap directory. A declared write copies the file's bytes into that snap first. When a llama-server this user started is listening, `begin` also saves its slot dumps, stops that pid only long enough to copy the closed files, and continues it. Agent-Reach is pinned in `pins.txt` and is not copied into this tree. `SIGSTOP` is sent only to pids this user owns. ZFS and btrfs are not invoked unless `FEELD_SNAP_FS` names one that is installed. There is no `adb` device on this host, so Android is still the detection test only. BitTorrent, trackers, rsync, and ssh are node names only until that block and `/local` exist.

Android is not a passed platform yet. The llama.cpp checkout detects Termux and `ANDROID_ROOT`. A live phone run has not been recorded here.
