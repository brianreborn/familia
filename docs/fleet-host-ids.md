# Fleet host IDs

Every fleet machine has one canonical **host ID**. Host lists, the registry,
deploy tooling and the fleet dashboard key on it; a hostname, ssh alias or graph
key is only a display label or lookup name.

## Format

    host ID:    <label-slug>-<fp8>                       e.g. note9-7140b66c
    host UUID:  128-bit RFC 4122 UUID (version-4 layout) e.g. 7140b66c-1c5a-4802-9105-604ae9117889

* `d = sha256("familia-hostid-v1|<anchor_type>|<anchor>")`; `host_uuid` is the first
  32 hex of `d` with the version nibble set to 4 and the variant to `10xx`, the same
  shape as systemd's `/etc/machine-id` but printed in RFC 4122 form.
* `fp8` = the first 8 hex of `host_uuid` (= first 8 hex of `d`), so the ID suffix is
  always the UUID prefix.
* `state-uuid` hosts (no readable hardware serial) use a random version-4 UUID as the
  host UUID directly; `fp8` is its first 8 hex.
* `registry/fleet-hosts.yaml` pins one `host_uuid:` line per host. `hostid.py check`
  requires a valid, unique v4 UUID per host whose prefix equals the ID suffix; all
  aliases of a host (ssh aliases, legacy graph keys) resolve to that one entry and UUID.
* The **fingerprint** (`fp8`) is the dedupe key. The label prefix is cosmetic, so
  a rename (phone7 -> galaxy1) still matches the same device.
* The raw anchor never leaves the machine and is never committed; only the salted
  8-hex hash is printed or stored.

## Anchors

The anchor is read on the device itself, so every transport (USB adb forward,
Wi-Fi, ethernet) reports the same value. IP addresses are never anchors, and MACs
are a last resort only (phones randomize them and USB tethering adds new ones).

| order | anchor_type    | source |
|-------|----------------|--------|
| 1 | android-serial | `getprop ro.serialno` / `ro.boot.serialno` (== adb serial) |
| 2 | soc-serial     | `/sys/devices/soc0/serial_number` (Termux-readable on Snapdragon) |
| 3 | android-id     | `settings get secure android_id` |
| 4 | machine-id     | `/etc/machine-id`, `/var/lib/dbus/machine-id` (Linux; FreeBSD 13+ also writes it) |
| 5 | hostuuid       | FreeBSD `kern.hostuuid`, `/etc/hostid` |
| 6 | platform-uuid  | macOS `IOPlatformUUID` |
| 7 | machine-guid   | Windows `HKLM\SOFTWARE\Microsoft\Cryptography\MachineGuid` |
| 8 | state-uuid     | `$XDG_STATE_HOME/familia/host-uuid`, created only by `hostid.py --init` |
| 9 | mac            | first physical NIC (weak) |
| 10 | hostname      | nothing readable: weak ID from the label (weak) |

Android 16 Termux (the A57s) exposes none of 1-3, so galaxy1 and galaxy2 have a
random v4 UUID pinned in the registry (anchor_type `state-uuid`). Their old weak
hostname IDs are listed under `previous_ids` so older probes still resolve. To make a phone report the
pinned ID itself, run `python3 scripts/fleet/hostid.py --init --init-value <host_uuid>`
on it (writes `$XDG_STATE_HOME/familia/host-uuid`; needs the owner's OK).

Standard path of the device ID file (one line, the v4 UUID, mode 600):

| platform | path |
|---|---|
| Linux, FreeBSD, macOS | `${XDG_STATE_HOME:-~/.local/state}/familia/host-uuid` |
| Termux (Android) | `/data/data/com.termux/files/home/.local/state/familia/host-uuid` |
| Windows | `%LOCALAPPDATA%\familia\host-uuid` |

galaxy1 and galaxy2 got this file on 2026-11-23 (owner approved), so they now report
galaxy1-845f9d5a and galaxy2-bd0351ec themselves.
When an anchor changes, move the entry to the new ID and list the old one under
`previous_ids`. The Grok Bot box gets a new machine-id when it is replaced.

## Label

`--label`, then `$FAMILIA_HOST_LABEL`, then the hostname pin
(`$XDG_STATE_HOME/familia/hostname`, see `scripts/hostname_pin.py`), then
`uname -n`. `localhost` becomes `host`.

## Tools

    sh scripts/fleet/hostid.sh [--label NAME] [--json] [--uuid]   # POSIX: Linux, Termux, FreeBSD, macOS
    python3 scripts/fleet/hostid.py [--label NAME] [--json]
    scripts\fleet\hostid.cmd [-Label NAME] [-Json]          # Windows (hostid.ps1)
    python3 scripts/fleet/hostid.py resolve note9-usb       # -> note9-7140b66c
    python3 scripts/fleet/hostid.py check                   # registry + graph.yaml links

## Registry

`registry/fleet-hosts.yaml` is keyed by host ID. Each entry keeps its label,
anchor type, aliases (ssh aliases, legacy graph keys) and a list of transports,
so one device with a USB and a Wi-Fi login is one entry with two transports.
Addresses and Termux accounts stay in the untracked `hosts.local.yaml` overlay (#104).

`graph.yaml` hosts carry `host_id:`. Legacy keys for the same device (phone7,
phone8) carry `alias_of:` and the same `host_id`; `hostid.py check` fails if two
graph hosts share a host ID without `alias_of`. Renaming the graph keys
themselves is a separate step (pins, overlays and allowlists still use them).

`scripts/swarm/deploy_fleet.py` resolves `--hosts` through the registry and
drops later aliases of a device it already has (note9 + note9-usb deploys once).

## Hostname pin vs registry

The machine-local hostname pin (`$XDG_STATE_HOME/familia/hostname`, one line read by
`scripts/hostname_pin.py`) only says which graph host this machine is; it stays one
line. The per-host UUID lines live in the registry. `tests/test_installers.py` used to
run `host_measure.py --name shalom --force` against the real state dir, which is how
miryam, angel and the box ended up pinned to `shalom`; it now uses a throwaway dir.
