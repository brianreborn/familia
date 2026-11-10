# hermes-agent pin

familia does not clone or install [hermes-agent](https://github.com/NousResearch/hermes-agent);
you install it (snap, FreeBSD `pkg install hermes-agent`, the upstream `install.sh`, or a venv).
familia does say **which release it targets**, per release channel, and checks the interpreter.

## Where the ref comes from

One hook, `scripts/hermes_pin.py` (`resolve_ref()`), is the only place a Hermes ref is chosen:

1. If `scripts/channel.py` (release channels) is in the tree, it validates
   `FAMILIA_CHANNEL=bleeding|stable` (default `bleeding`) and `FAMILIA_STABLE_DAYS=N`, and resolves
   the `hermes-agent` source: bleeding = newest non-prerelease, stable = most stable release in
   the last N days. If the network fails, the channel's pin below is used (`fallback: true`).
2. Otherwise, or with `--offline`, the channel-keyed pin in `config/hermes-agent.pins.json` is used.

An invalid channel or day count is an error (exit 2), never a silent default.

| Channel | Ref | Commit | Notes |
|---|---|---|---|
| bleeding (default) | `v0.22.6` | `f0d94882e89a` | equal to upstream `main` on 2026-11-02 |
| stable | `v0.22.5` | `bf0203a794a0` | channel.py stable (30 days) on 2026-11-02 |

Python floor: **3.14** (upstream declares its dependencies only for python >= 3.14).

```sh
python3 scripts/hermes_pin.py resolve                       # ref for the effective channel
FAMILIA_CHANNEL=stable python3 scripts/hermes_pin.py resolve --json
python3 scripts/hermes_pin.py check                         # installed `hermes --version` vs the pin
```

`check` exits 1 on a mismatch and prints how to install the wanted ref with upstream's
installer (`install.sh --commit <commit>`), downloaded first and then run, from that same commit
(`raw.githubusercontent.com/NousResearch/hermes-agent/<commit>/scripts/install.sh`, never the moving
`hermes-agent.nousresearch.com/install.sh`); familia itself never installs hermes. snap and
FreeBSD packages follow their own versions, so for those it only warns.

The pin file is validated on every read: each `commit` is 40 lowercase hex (it is printed inside a
shell install command), both `bleeding` and `stable` entries must exist (a missing stable entry is an
error, not a quiet fall back to bleeding), and unreadable or malformed JSON is a one-line error
(exit 2), not a traceback.

## At launch (`scripts/hermes.sh`)

- The full `hermes` CLI is used. In pip/uv/install.sh layouts `hermes-agent` is upstream's legacy
  single-query runner (`agent.legacy_cli`, no `-z`/`-t`/`desktop`/`webapp`); when it is what PATH
  finds and a `hermes` sits beside it, that `hermes` is launched instead. An explicit `HERMES_BIN`
  still wins, with a warning.
- A warning when `HERMES_PY` is older than the python floor.
- `FAMILIA_HERMES_PIN_CHECK=1` also compares the installed version with the channel's pin
  (offline, no network at launch); `=strict` refuses a mismatch.
  `FAMILIA_HERMES_TOOLCHAIN_CHECK=0` skips both checks.

## Checking a new upstream release

Install the tag into a venv (`uv sync --frozen --no-dev` in a checkout of the tag), then:

```sh
FAMILIA_HERMES_UPSTREAM_PY=/path/to/venv/bin/python python3 -m pytest tests/test_hermes_upstream_compat.py
```

That loads the rendered HERMES_HOME with that hermes (config schema incl. `mcp_servers` and
`approvals`, toolsets, MCP `${VAR}` interpolation, aux routing, skills, child-process symbols).
Then update the channel's entry in `config/hermes-agent.pins.json`.

`vision`, `voice_chat`, `moa_reference` and `moa_aggregator` are also pinned to the local node, and
Mixture of Agents is disabled with a local-only `moa.presets.default` (upstream's built-in preset
uses openai-codex and openrouter). A node without vision or voice fails those tasks locally instead
of upstream's `auto` falling through to a cloud provider. The same local-only render also sets
`auxiliary.free_only: true` and `auxiliary.openrouter_model: disabled` so hermes-agent's
OpenRouter aux auto-chain is skipped (upstream stock default is a hosted SKU such as
Gemini on OpenRouter). `providers` and `custom_providers` are written empty;
`fallback_model` and `smart_model_routing` stay omitted so they stay disabled. Cloud LLM credentials are removed from
the hermes child environment: every env name the installed hermes-agent's provider registry declares
(`hermes_cli/auth.py` rows and `plugins/model-providers/*` `env_vars`, parsed from its source, never
imported), plus a static superset (`*_API_KEY`, `*_API_TOKEN`, `ANTHROPIC_TOKEN`,
`CLAUDE_CODE_OAUTH_TOKEN`, `HF_TOKEN`, `GOOGLE_APPLICATION_CREDENTIALS`, every `AWS_*`; `FAMILIA_*`
kept). File-based chains are pointed away: `AWS_SHARED_CREDENTIALS_FILE` / `AWS_CONFIG_FILE` =
`/dev/null`, `AWS_EC2_METADATA_DISABLED=true`, and `CODEX_HOME` / `CLOUDSDK_CONFIG` = empty private
dirs under `HERMES_HOME/.no-cloud-creds/`. Credentials found only through `$HOME` (`~/.qwen/oauth_creds.json`,
`~/.claude`) are not redirected (that would mean moving the child's HOME). MCP secrets the graph
declares (`env_from`, `headers_from`) are kept.

Ambient non-LLM secrets are not carried into hermes (and so not into its terminal tool) either:
`GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN`, `GITHUB_ENTERPRISE_TOKEN`, `SSH_AUTH_SOCK`,
`DSN`, `DATABASE_URL`, `KUBECONFIG`, `REDIS_URL`, `AMQP_URL`, `RABBITMQ_URL`, `CLOUDAMQP_URL`,
`MONGODB_URI`, `PGPASSWORD`, `MYSQL_PWD`, and any `*_SECRET`, `*_SECRET_KEY`, `*_PASSWORD`,
`*_PASSWD`, `*_PWD`, `*_TOKEN`, `*_PRIVATE_KEY`, `*_DSN`, `*_DATABASE_URL`, `*_DB_URL`,
`*_REDIS_URL`, `*AMQP*_URL`/`_URI`, `MONGO*`/`POSTGRES*`/`MYSQL*`/`RABBITMQ*_URL`/`_URI`.
Secret-shaped names are matched before any keep list, so `FAMILIA_GH_TOKEN` and `HERMES_TOKEN`
drop too. Any var whose value has URL userinfo (`scheme://user:pass@…` or `scheme://token@host`,
no colon required) is also dropped (plain URLs such as a local llama endpoint are kept). `*_URI`
is value-based: dropped only when the value has userinfo or a known credential DSN scheme
(`postgres://`, `mongodb://`, `redis://`, `amqp://`, …); names like `REDIRECT_URI` stay.
Graph-declared MCP names and harness control vars (`HERMES_HOME`, `FAMILIA_API_KEY`, …) are kept.
`FAMILIA_HERMES_PASS_SECRETS=1` passes them through (for example `git push` over ssh from the agent). `FAMILIA_HERMES_ALLOW_CLOUD=1` restores upstream behaviour for all of
this (auto routing, the user's `moa` section, keys passed through).
