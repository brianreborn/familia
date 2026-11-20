# swarm: miryam Bluetooth transport (BlueZ RFCOMM/BLE GATT to phones)

Issue: https://github.com/brianreborn/familia/issues/385
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 08:20 PST
Approved-content-sha256: 5ff5426b424e11b1858ecbce27ca7f8a44aff63502e7ba29dbad70e2b8a8d72d

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

# miryam Bluetooth probe (read-only, no pairing or scan-on)

Linked: umbrella #382, design #380, issue #385.
No pairing, unpairing, discoverable-mode, or scan-on was performed.

## Host
stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.6-live mode=live
uname: Linux aarch64 6.12.69-android16-6-p902157d-abogkiA576USQS4BZJ2-4k

## Tools and stack
### tool presence
$ command -v bluetoothctl; command -v btmgmt; command -v hciconfig; command -v rfcomm; command -v btmon; command -v hcitool
rc=127

### bluetoothctl version
$ bluetoothctl --version 2>&1
rc=127
/bin/sh: 1: bluetoothctl: not found


### modules (bluetooth/rfcomm/btusb)
$ lsmod 2>/dev/null | grep -i -E 'bluetooth|rfcomm|bnep|btusb|btintel|btrtl|btbcm' || true
rc=0

### sys class
$ ls -l /sys/class/bluetooth 2>/dev/null; ls /sys/class/bluetooth 2>/dev/null
rc=2

## RFCOMM vs BLE GATT feasibility
RFCOMM: classic Bluetooth serial profile. Good fit for a line-oriented
ASCII/JSON envelope (claim, heartbeat, result). Typical SPP throughput is
tens to a few hundred kbit/s; latency tens of ms when connected. Needs
pairing/bonding on first use. BlueZ exposes /dev/rfcomm* after `rfcomm bind`
(that bind is a state change and was NOT done).
BLE GATT: lower power, smaller MTU (default 23 bytes ATT, often negotiated
to 185-512). A compact claim line can be one write; a report needs
segmentation. Better for phones already using BLE; more design work.
Recommendation: use RFCOMM for bulk/result and optional BLE for short
claim/heartbeat if classic is blocked, once pairing is approved.

## Pairing (described, not executed)
1. Report intent (this issue). Wait for Brian's OK.
2. bluetoothctl: power on (if off -- report first), pair <addr>, trust <addr>.
3. On each phone, accept the pair in the system Bluetooth UI.
4. Only then bind RFCOMM or register a GATT service.
No step after (1) was taken.

## Range / performance sketch (typical, not measured here)
Class-2 Bluetooth (common in laptops and phones): about 10 m line-of-sight,
often a room or two indoors, less through walls. Source: Bluetooth SIG class-2
typical +10 dBm / 10 m figure. Throughput and range must be measured after an
approved pair; nothing was paired or pinged this run.

## Store-and-forward
If the phones are out of range or BT is down, write ~/swarm/outbox and
retry. Sync to GitHub when WAN returns. Local wall clocks are not used
for lease expiry (design #380).

## 2. Local model draft (unverified)



-- swarm/galaxy1
