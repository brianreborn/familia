# Hosts connection overlay (#104)

Tracked `graph.yaml` must not contain real per-host connection details (LAN
addresses, login account names, Termux `u0_a*` users). Those fields are
placeholders (`REPLACE_ME`) or omitted in git. Real values live in a **local
overlay** merged at load time.

## Where the overlay lives

Lookup order (first existing file wins):

1. `$FAMILIA_HOSTS_OVERLAY` — explicit path
2. Config dir `hosts.local.yaml`
   - POSIX / Termux: `$XDG_CONFIG_HOME/familia/hosts.local.yaml` (default `~/.config/familia/hosts.local.yaml`)
   - Windows: `%LOCALAPPDATA%\familia\hosts.local.yaml`
3. Repo-root `hosts.local.yaml` next to `graph.yaml` (gitignored)

This matches the private `~/.config/familia/monitor.json` pattern used by
`scripts/monitor.py`. The machine-local hostname pin
(`scripts/hostname_pin.py` → state dir `hostname`) is separate: it selects
*which* graph host this machine is, not how to reach peers.

## Keeping the overlay across `./familia update`

`./familia update` is `git pull --ff-only` plus pin sync. It does **not** touch
files under `~/.config/familia/` or `%LOCALAPPDATA%\familia\`. A repo-root
`hosts.local.yaml` is gitignored, so it also survives pull. Prefer the config-dir
location so a fresh clone still works after you copy the overlay once.

```sh
mkdir -p ~/.config/familia
cp hosts.local.yaml.example ~/.config/familia/hosts.local.yaml
# edit addr / user / port for your LAN
python3 scripts/hosts_overlay.py show --graph graph.yaml
```

## What is merged

| Overlay key | Merged into |
|-------------|-------------|
| `hosts.<name>.addr` | `graph.hosts.<name>.addr` |
| `hosts.<name>.user` | `graph.hosts.<name>.user` |
| `hosts.<name>.port` | `graph.hosts.<name>.port` |
| `meshes.<name>.bind` | `graph.meshes.<name>.bind` (optional) |

If `meshes.*.bind` is still a placeholder after merge, BitTorrent meshes fill
`bind` from the tracker host's `addr`.

Consumers that load through `validate_graph.py`, `transport_graph.load`,
`android_target.py`, or `hosts_overlay.load_graph_with_overlay` see the merged
graph. `monitor.py` also merges before the optional `allow_graph_addr` path.

## CI / validator

`python3 scripts/validate_graph.py` (and `hosts_overlay.py lint`) fail if the
**tracked** graph still contains:

- RFC1918 / link-local / unique-local IP literals
- Termux `u0_a*` account names
- Non-placeholder `hosts.*.user` or concrete IP `hosts.*.addr` / `meshes.*.bind`

History rewriting to scrub past commits is **optional and out of scope** for the
#104 PR; rotate credentials if exposure matters.

## Example

See [`hosts.local.yaml.example`](../hosts.local.yaml.example) at the repo root.
