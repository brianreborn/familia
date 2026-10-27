# Angel / Uriel operator path — Nanbeige multi-node (not limp mode)

**Coordinator:** FreeBSD host `angel` (aka **Uriel**; SSH `Host angel gabriel` → `192.168.1.3`).  
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
