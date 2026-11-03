# Installing familia on FreeBSD

One file, verified before it runs. Never pipe it into a shell.

```
p=familia                          && \
o=brianreborn                      && \
h=raw.githubusercontent.com        && \
u=https://$h/$o/$p/main/install/freebsd/install-$p.sh && \
fetch -o install-$p.sh $u          && \
sha256 -q install-$p.sh            && \
sh        ./install-$p.sh
```

Compare the `sha256 -q` output with the SHA256 published in the release
notes before the last line runs; stop if it differs. (`curl -fsSLo` and
`sha256sum` work in place of `fetch` and `sha256` off FreeBSD.)

```
p=familia && o=brianreborn && h=raw.githubusercontent.com && u=https://$h/$o/$p/main/install/freebsd/install-$p.sh && fetch -o install-$p.sh $u && sha256 -q install-$p.sh && sh ./install-$p.sh
```

Usage (from `--help`):

```
usage: sh ./install-familia.sh [flags]
  --prefix DIR  install root
                (default ~/.local/share/familia)
  --branch REF  familia branch/tag (main)
  --auto-deps   allow pkg install via
                sudo/doas (asks first)
  --yes         accept defaults (not root)
  --dry-run     print actions, change nothing
  --uninstall   remove repo + launcher
```

Prerequisites (pkg): git python3 py311-pyyaml llama-cpp. Without
`--auto-deps` the installer halts and lists them. llama-server binds
loopback only and always needs `~/.config/familia/api.key` (0600).

Tested: syntax (sh, dash, shellcheck -s sh) and dry-run/fake-shim runs on
Linux. FreeBSD itself: partial tested (not yet run on a FreeBSD host).

Screenshots: to be captured from a real FreeBSD run (docs/screenshots/).
