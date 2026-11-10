# Contributing

## Config is a contract (CFG-RULE-001)
Every config file and every program that reads or writes one is described in [docs/config/](docs/config/README.md), with stable requirement IDs (`CFG-…-NNN`).
**Any change to a config file, its schema (`scripts/graph_types.py`) or its consumers must update docs/config and `docs/config/requirement-ids.yaml` in the same PR.**
- New graph field: run `python3 scripts/config_docs.py --write`, then add semantics/invariants by hand.
- New requirement ID in docs: run `python3 scripts/config_docs.py --register`.
- SPEC → IMPLEMENTED: flip the status and add a `file:line` pointer and a test that cites the ID.
- CI/offline gate (CFG-RULE-002): `tests/test_config_docs.py` runs `scripts/config_docs.py --check`.
- No IPs, usernames, ports or keys in tracked files (docs/config/credentials.md).

Process: branch `swarm/<owner>/<topic>` from origin/main, open a PR with `Fixes #N`, no merge without Brian's explicit yes (#151).

## Console and log output style (ASCII/ANSI house style)

Applies to new PRs. Chrome only: user and model text stays UTF-8.

### Before you open a PR

- [ ] Console/log chrome picks its glyph tier at runtime: Unicode box/blocks on UTF-8,
      cp437 bytes on an OEM console, 7-bit `+-|#` for pipes, logs and unknown encodings.
- [ ] No em dash, emoji or arrow in console/log output without a fallback (they are not in cp437).
- [ ] ANSI color only on a TTY with NO_COLOR unset and TERM != dumb; always reset with ESC[0m; no color in logs.
- [ ] Banners are <=78 columns, contain no tabs, and are skippable (--quiet or not on a TTY).
- [ ] User and model text stays UTF-8; these rules cover chrome only.
- [ ] Art is authored once as cp437 bytes; tiers are derived through one shared helper (~30 lines) per language.
- [ ] No new dependency added only for terminal chrome/colour.

### Reviewer checklist

- [ ] BLOCKING: a decorative glyph emitted on a console/log path without tier selection.
      Spot-check: `LC_ALL=C grep -n '[^ -~	]' FILE`
