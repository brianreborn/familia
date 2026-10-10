# Transport PoC: SSH nexus and private BitTorrent tracker

Refs #22 (C2C, stage 1: move llama.cpp slot-save KV files and model files between
nodes), #5 (transports), DESIGN.md "Transports". The key names the object, the edge
names how it moves, and the user picks the edge: nothing here auto-selects a
transport. Both are declared in `graph.yaml` under `hosts:` and `meshes:` and
checked by `scripts/validate_graph.py` (via `scripts/transport_graph.py`).

Naming: green-roomz calls the resident `route` model "the nexus" (DESIGN.md,
green-roomz `policies/tool-router.md`). `lan-nexus` here is the *transport* hub that
the hosts in the graph meet at. It is a store, not a model.

## Graph entries

```yaml
hosts:
  miryam: {addr: 192.168.1.9, user: rcs,     port: 22,   kind: desktop}  # measured on miryam
  phone7: {addr: 192.168.1.7, user: u0_a439, port: 8022, kind: phone}
  phone8: {addr: 192.168.1.8, user: u0_a414, port: 8022, kind: phone}
meshes:
  lan-nexus: {type: ssh, hub: miryam, root: ~/.familia/nexus, identity: ~/.ssh/id_ed25519,
              host_key_policy: accept-new, members: [miryam, phone7, phone8]}
  lan-bt:    {type: bittorrent, tracker: miryam, bind: 192.168.1.9, port: 6969,
              private: true, client: aria2c, members: [miryam, phone7, phone8]}
```

The validator fails on: unknown transport type, undeclared hub/tracker/member, any
`password` field, `host_key_policy` other than accept-new/yes, tracker bind of
0.0.0.0 or a public address, bind not equal to the tracker host's addr,
`private: false`, an unsupported client, and any missing host field (no defaults).

## SSH nexus (`scripts/nexus/nexus.py`)

The hub is a directory on one host: `<root>/peers/<host>.json` and
`<root>/artifacts/<sha256>/{<file>,meta.json}`. Members use ssh and rsync only, with
`BatchMode=yes`, `IdentitiesOnly=yes`, `PasswordAuthentication=no`,
`StrictHostKeyChecking=accept-new`. Artifacts are keyed by sha256 and verified on
the hub after `put` and locally after `get`, and a mismatch deletes the copy.

```sh
N="python3 scripts/nexus/nexus.py --graph graph.yaml --transport lan-nexus"
$N --as phone7 register
$N --as phone7 peers
$N --as miryam put ~/.cache/llama/slots/coder-slot0.bin --kind kv   # prints sha256
$N --as phone8 ls
$N --as phone8 get <sha256-prefix-or-name> ~/kv/
```

## Private tracker + aria2c (`scripts/bt/`)

* `tracker.py --bind 192.168.1.9 --port 6969 --allow-dir ~/.familia/bt/allow`: HTTP
  announce with compact peers. It only tracks infohashes that have `<hex>.torrent` in the
  allow dir, and it refuses to bind 0.0.0.0 or a public address.
* `mktorrent.py FILE --announce http://192.168.1.9:6969/announce --out-dir ~/.familia/bt/t --allow-dir ~/.familia/bt/allow`
  makes a private (`private=1`) torrent and prints the REQ-REPO-02 key
  `magnet:urn:btih:<40hex>:<path-inside-torrent>`.
* `seed.sh T.torrent DATA_DIR 6881` uses aria2c with DHT, PEX, and LPD off.
* `fetch.sh KEY http://192.168.1.9:6969/announce DEST 6882 [SHA256]` turns the key into a
  magnet URI, gets the metadata from the seeder (BEP 9), downloads, and checks sha256.

Run the tracker on the host where you create torrents, or copy the `.torrent` into
the tracker's allow dir (the nexus `put` works for that).

## Running on miryam

```sh
sudo apt install openssh-server rsync aria2 python3-yaml
python3 scripts/validate_graph.py            # set hosts.miryam.addr to the real LAN IP first
python3 scripts/bt/tracker.py --bind <miryam-ip> --port 6969 --allow-dir ~/.familia/bt/allow
```

## Running on the Android phones (Termux)

```sh
pkg install openssh rsync aria2 python && pip install pyyaml
sshd                                   # listens on :8022
# once per phone: add miryam's key (from familia chat), and generate the phone's own key
ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519
# append the phone's ~/.ssh/id_ed25519.pub to the hub user's ~/.ssh/authorized_keys on miryam
termux-wake-lock                       # keep seeding while backgrounded
```

Status: on 2026-10-09 both phones (192.168.1.7 u0_a439, 192.168.1.8 u0_a414) answer on
:8022 but do not have miryam's key installed yet, so phone tests have not run.
Phones are clients of the nexus (they reach the hub's `:22`). They do not need to be
reachable themselves, except as BitTorrent peers on their aria2c `--listen-port`.

## Tests (run on the box)

* `tests/test_bt_loopback.sh` runs the tracker, a seeder, and a leecher on 127.0.0.1 with a
  24 MiB file fetched by key. sha256 matches, and an unregistered infohash is refused.
* `tests/test_nexus_localhost.sh` runs a throwaway key-only sshd on 127.0.0.1:2222 and
  three unix users (hub, a, b). It covers register, peers, put, ls, and get with sha256
  matching, and refuses a non-member and a user without an authorized key (publickey only,
  no password prompt). It needs sudo.
* `tests/test_transport_validator.py` checks the shipped graph and 9 rejection cases.

## Gaps

* No auth on the tracker beyond LAN bind + allow-list (no passkeys); fine for a PoC.
* In-memory peer table; restart loses peers until the next announce (30 s).
* Single-file torrents only; multi-file paths-inside-torrent are not built yet.
* Nexus has no locking; two `put`s of the same sha are idempotent, different files never collide.
* Stage 2 of #22 (projected KV between different models) needs a transformers/vLLM runtime.
