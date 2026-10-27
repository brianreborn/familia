# Angel / Uriel operator path — Nanbeige multi-node (not limp mode)

**Coordinator:** FreeBSD host `angel` (aka **Uriel**; SSH `Host angel gabriel` → `192.168.4.25`).  
After `98633d5`: `angel-coder` **active**, `angel-chat` **planned**, weights present, `local_names` include uriel.

## Prefer the graph, not limp mode
Default is **multi-node**: box (decision+coder) + **one** Nanbeige role on angel.  
`hermes --model NODE` / single-model mode is a **last resort**, not the restart path.

## Sync → start (angel)
```sh
cd ~/familia   # or ~/familia/repo
git fetch origin main && git pull --ff-only origin main
./familia sync   # or: python3 scripts/sync_pins.py --auto
python3 scripts/validate_graph.py --no-files
python3 scripts/validate_graph.py --host angel
python3 scripts/validate_graph.py --host angel --check-swap  # needs ≥ swap_budget_mib
mkdir -p ~/.cache/familia/spill/angel-coder
swapinfo -k   # ~24 GiB familia swap or proven RSS headroom
./start.sh --host angel --yes
curl -sS http://127.0.0.1:18200/health   # angel-coder only
```
Do **not** co-start `angel-chat` on 24 GiB. Spill/mmap: [LAYER.md](./LAYER.md).

## Many-node fleet shape
| Host | Nodes | Ports |
|------|-------|-------|
| box | box-decision, box-coder | 18120 / 18121 |
| angel/Uriel | angel-coder XOR angel-chat | 18200 / 18201 |
| miryam | coder, embed, … | per graph |

Progress-to-issues agents: pull tip `98633d5`+, then sync/start as above — skip limp `--model` unless the graph fails hard.

## Hermes on angel (non-snap)

`pkg install hermes-agent` (misc/hermes-agent) installs:

- `HERMES_BIN=/usr/local/bin/hermes-agent` (wrappers also: `hermes`, `hermes-acp`)
- `HERMES_PY=/usr/local/bin/python3.12` (wrapper shebang)
- `HERMES_SP=/usr/local/lib/hermes-agent` (ports libdir — **not** site-packages)

The familia harness auto-detects this; export the three vars only to override. Smoke without box GGUFs:

```sh
cd ~/familia
scripts/hermes.sh --model angel-coder --render-only
# or: python3 scripts/validate_graph.py --host angel
```

**min_ctx:** `agents.hermes.min_ctx` is 64000 (upstream `MINIMUM_CONTEXT_LENGTH`). `angel-coder` is ctx **65536** (Brian #125: mmap + spill + `swap_budget_mib` 24576; accept heavier SSD spill). Do not lower `min_ctx`. Live `--check-swap` / activate still on angel SSH.

