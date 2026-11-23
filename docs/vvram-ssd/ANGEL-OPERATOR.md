# Angel / Uriel operator path — qualified graph deployment

**Coordinator:** FreeBSD host `angel` (aka **Uriel**; use the local SSH alias and private host inventory for its address).

## Design law (private topology)

Node **type** implies capability (`coder`, `chat`, …). Placement is `host:`, not
host-prefixed ids. On angel the private graph is:

| Type key | Fleet node | Model | Status | Port |
|----------|------------------------|-------|--------|------|
| `coder` | `angel-coder` | `qwen35-2b-q4km` | planned pending 262144-context RAM qualification | 18200 |
| `chat` | `angel-chat` | `gpt-oss-20b-mxfp4` | planned pending 131072-context RAM/swap qualification | 18201 |
| `guardian` | `freebsd-guardian` | `dolphin3-cyber-8b-q2k` | planned pending local weights and ready-check | 18203 |

```sh
python3 scripts/generate_graph.py angel          # → generated/graph-angel.yaml
python3 scripts/modify_graph.py --host angel --list
python3 scripts/generate_graph.py angel          # → generated/graph-angel.yaml
python3 scripts/validate_graph.py --graph generated/graph-angel.yaml --host angel --check-runtimes
python3 scripts/start_graph.py --graph generated/graph-angel.yaml --host angel --dry-run
```

Both model nodes remain planned until the complete native context fits the measured
RAM and swap policy. Do not shorten the documented context to force a launch. The
Guardian node has separate weight/license readiness gates. Angel's local Green-Roomz
gateway can route only after a qualified node is activated.

## Prefer the graph, not limp mode
Default is the explicit fleet graph: Miryam hosts Hermes and its coder aliases;
Angel's local graph carries only Angel placements. Private graphs do not clone
agents between hosts.

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
curl -sS http://127.0.0.1:18200/health   # only after coder activation
```

Spill/mmap: [LAYER.md](./LAYER.md).

## Many-node fleet shape
| Host | Private type nodes | Ports |
|------|-------------------|-------|
| box | decision, coder | 18120 / 18121 |
| angel/Uriel | coder XOR chat | 18200 / 18201 |
| miryam | coder, embed, … | per graph |

## Hermes placement

Hermes remains explicitly assigned to Miryam, whose coder alias and 65536-token
agent context agree. Angel does not receive a cloned Hermes agent. Place one only
after its selected coder model, full context, RAM and transport path are qualified.

## Offline useful

If angel loses fleet SSH peers, keep it busy with the offline improve loop
([offline-improve.md](../offline-improve.md)):

```sh
python3 scripts/offline_improve.py --host angel --loop
```

Does not start a model; benches a small GGUF + host RAM, persists under
`~/.local/state/familia/offline-improve/angel/`, retries reconnect with backoff.
