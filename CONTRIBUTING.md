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
