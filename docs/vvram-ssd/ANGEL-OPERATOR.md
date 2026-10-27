# Angel / Uriel operator path — Nanbeige multi-node (not limp mode)

**Coordinator:** FreeBSD host `angel` (aka **Uriel**; SSH `Host angel gabriel` → `192.168.4.25`).

## Design law (private topology)

Node **type** implies capability (`coder`, `chat`, …). Placement is `host:`, not
host-prefixed ids. On angel the private graph is:

| Type key | Fleet transitional key | Model | Status | Port |
|----------|------------------------|-------|--------|------|
| `coder` | `angel-coder` | `nanbeige43-33b-q4km` | active | 18200 |
| `chat` | `angel-chat` | `nanbeige43-33b-q4km` | planned | 18201 |

```sh
python3 scripts/generate_graph.py angel          # → generated/graph-angel.yaml
python3 scripts/modify_graph.py --host angel --list
python3 scripts/modify_graph.py --host angel --assign-model coder=nanbeige43-33b-q4km
./start.sh --host angel --dry-run                # uses private topology (type names)
./start.sh --host angel --fleet --dry-run        # transitional fleet keys
```

Do **not** co-start `coder` and `chat` on 24 GiB. Multi-node **fleet** shape is
box + angel + miryam graphs — not limp `--model` single-node mode.

## Prefer the graph, not limp mode
Default is **multi-node fleet**: box (decision+coder) + **one** Nanbeige role on
angel (`coder` XOR `chat`) + miryam coder/embed.  
`hermes --model NODE` / single-model mode is a **last resort**, not the restart path.

## Sync → start (angel)
```sh
cd ~/familia
git fetch origin main && git pull --ff-only origin main
./familia sync
python3 scripts/generate_graph.py angel
python3 scripts/validate_graph.py --graph generated/graph-angel.yaml --no-files
python3 scripts/validate_graph.py --host angel --fleet   # or against private graph
mkdir -p ~/.cache/familia/spill/angel-coder
swapinfo -k
./start.sh --host angel --yes
curl -sS http://127.0.0.1:18200/health   # coder only
```

Spill/mmap: [LAYER.md](./LAYER.md).

## Many-node fleet shape
| Host | Private type nodes | Ports |
|------|-------------------|-------|
| box | decision, coder | 18120 / 18121 |
| angel/Uriel | coder XOR chat | 18200 / 18201 |
| miryam | coder, embed, … | per graph |

## Hermes on angel (non-snap)

`pkg install hermes-agent` then:

```sh
cd ~/familia
scripts/hermes.sh --model coder --render-only   # private type name after generate
# transitional fleet: scripts/hermes.sh --model angel-coder --render-only
```

**min_ctx:** `agents.hermes.min_ctx` is 64000. Angel `coder` ctx is **65536** (Brian #125).

## Offline useful

If angel loses fleet SSH peers, keep it busy with the offline improve loop
([offline-improve.md](../offline-improve.md)):

```sh
python3 scripts/offline_improve.py --host angel --loop
```

Does not start Nanbeige; benches a small GGUF + host RAM, persists under
`~/.local/state/familia/offline-improve/angel/`, retries reconnect with backoff.

