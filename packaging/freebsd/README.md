# FreeBSD port (preliminary)

Overlay ports tree containing `sysutils/familia`. Target: FreeBSD 15.x
(godslove, green-roomz#5). **Nothing here has been built on FreeBSD yet.**

## Build stand-alone with poudriere
```sh
poudriere jail  -c -j 151amd64 -v 15.1-RELEASE -a amd64
poudriere ports -c -p default -m git+https -B main
poudriere ports -c -p familia -m null -M "$PWD/packaging/freebsd"
cd packaging/freebsd/sysutils/familia && make makesum   # regenerate distinfo
poudriere bulk  -j 151amd64 -p default -O familia sysutils/familia
```
`-O familia` overlays this tree on the main ports tree, so poudriere builds
every RUN_/BUILD_DEPENDS (python, py-pyyaml, bash, git, rsync, curl, and
optionally misc/llama-cpp, www/aria2, graphics/vulkan-loader) automatically.
`scripts/freebsd/poudriere-build.sh [-n]` does the same idempotently.

## Options
| Option | Default | Pulls in |
|---|---|---|
| LLAMA | on | misc/llama-cpp (`llama-server`) |
| BITTORRENT | off | www/aria2 |
| VULKAN | off | graphics/vulkan-loader; also set `misc_ggml_SET=VULKAN` (default-on in misc/ggml) |
| DOCS / EXAMPLES | on | docs to DOCSDIR, graph.yaml to EXAMPLESDIR |

## rc.d
`familia_server` is disabled by default: `sysrc familia_server_enable=YES`.

## Verified off-FreeBSD (2026-10-09)
- All dependency origins exist in freebsd/freebsd-ports main.
- Makefile parses under bmake with a stubbed bsd.port.mk; do-install expands.
- rc script and helper pass `sh -n`; helper dry-run works.

## TBD
- `make makesum` / real distinfo; GH_TAGNAME pinned to a release tag.
- portlint, `make stage check-plist`, poudriere testport.
- LICENSE value (set as UNKNOWN pending review).
- rc.d pidfile/daemon behaviour; whether start.sh's subproject fetches (git
  clone at runtime) are acceptable in a port or need a separate flavor.

## Hermes clients on FreeBSD (ordinary port notes)

This port ships **familia**, not Hermes Desktop. Native Hermes Desktop (Electron)
targets macOS / Windows / Linux — no familia FreeBSD Electron port is required.

On FreeBSD, treat Hermes as an ordinary frontend client:

- **CLI** — install/resolve `hermes-agent` (ports / `HERMES_BIN`); launch via
  `scripts/hermes.sh` (default `--client cli`).
- **Webapp** — when the installed Hermes build provides `webapp`, use
  `scripts/hermes.sh --client webapp` and open the one-use browser link
  (upstream documents BSD/illumos link-file behaviour).

Details: [`docs/hermes-clients.md`](../../docs/hermes-clients.md).
