# Installing familia on FreeBSD

One file, verified before it runs. Never pipe it into a shell.

```
p=familia                          && \
o=brianreborn                      && \
r=v0.2                             && \
h=raw.githubusercontent.com        && \
u=https://$h/$o/$p/$r/install/freebsd/install-$p.sh && \
e=PASTE_SHA256_FROM_SHA256SUMS     && \
fetch -o install-$p.sh $u          && \
[ "$(sha256 -q install-$p.sh)" = "$e" ] && \
sh        ./install-$p.sh
```

`r` is the v0.2 release tag (or the pinned `FAMILIA_REF` commit sha baked
into the script), never `main`. `e` is the `install-familia.sh` line of
that release's `SHA256SUMS` (published per familia#293). If the
hash differs, the `[ ... ]` test fails and the installer never runs. Off
FreeBSD, use `curl -fsSLo install-$p.sh $u` and
`[ "$(sha256sum install-$p.sh | cut -d' ' -f1)" = "$e" ]`.

```
p=familia && o=brianreborn && r=v0.2 && h=raw.githubusercontent.com && u=https://$h/$o/$p/$r/install/freebsd/install-$p.sh && e=PASTE_SHA256_FROM_SHA256SUMS && fetch -o install-$p.sh $u && [ "$(sha256 -q install-$p.sh)" = "$e" ] && sh ./install-$p.sh
```

Usage (from `--help`):

```
usage: sh ./install-familia.sh [flags]
  --prefix DIR  install root
                (default ~/.local/share/familia)
  --auto-deps   allow pkg install via
                sudo/doas (asks first)
  --yes         accept defaults (not root)
  --dry-run     print actions, change nothing
  --uninstall   remove repo + launcher
```

Prerequisites (pkg): git python3 (or python3.11) py3XX-pyyaml (XX from
the installed Python), and to build llama.cpp: cmake, c++ (base clang or
llvm). Without `--auto-deps` the installer halts and lists them.

Pins: familia is checked out at the `FAMILIA_REF` sha baked into the
script and `git rev-parse HEAD` is verified. llama.cpp is built from
source at tag b11969 (`c3df4b7e22a1ac38da663552d19e649dd97ca936`, verified)
into `~/.local/share/familia/runtime/b11969/` (an existing build there is
reused); the FreeBSD `llama-cpp` pkg is not used. The installer and
launcher refuse a llama-server whose `--help` lacks `--api-key-file`.

Launcher (`~/.local/bin/familia-start`): loopback only (`localhost` maps
to 127.0.0.1), API key `~/.config/familia/api.key` required (0600, owned
by you, not a symlink), `LLAMA_API_KEY` and every `LLAMA_ARG_*` scrubbed,
FAMILIA_EXTRA/argv `--host* --port* --api-key* --ssl* --path*` refused,
FAMILIA_MODEL a bare name in models/ or an absolute existing file (no `..`),
an unset or C/POSIX locale gets LC_CTYPE=C.UTF-8 (and LANG=C.UTF-8;
LC_ALL=C/POSIX is dropped so it cannot mask LC_CTYPE).

Rebuild guard: a reused llama-server must have `runtime/b11969/.built-sha`
equal to the pinned sha and a `--version` naming 11969 or c3df4b7, else
it is rebuilt. `FAMILIA_REF_OVERRIDE` is test-only: honored with
`--dry-run` or `FAMILIA_TEST_MODE=1`, refused otherwise.

Tested: sh -n, dash -n, shellcheck -s sh, and fake-shim runs on Linux
(tests/test_freebsd_installer.py). FreeBSD itself: partial tested (not yet
run on a FreeBSD host; the llama.cpp source build was not exercised).

Screenshots: to be captured from a real FreeBSD run (docs/screenshots/).
