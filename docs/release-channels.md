# Release channels

familia can follow its dependencies on one of two channels.

| Channel | What you get |
|---|---|
| `bleeding` (default) | Today's behavior, unchanged: installers and fetchers do exactly what they did before channels existed. |
| `stable` | For each dependency, the most stable release published in the last N days (default 30). No release numbers are pinned, so the choice keeps moving forward on its own. |

## Choosing a channel

| Setting | Environment | Installer flag |
|---|---|---|
| Channel | `FAMILIA_CHANNEL=bleeding\|stable` | `--channel bleeding\|stable` (`install.sh`, `install/linux/install.sh`) |
| Window | `FAMILIA_STABLE_DAYS=N` | `--stable-days N` |

An explicit flag wins over the environment, which wins over the default.
Input is checked strictly: the channel must be exactly `bleeding` or `stable`,
and N must be a plain base-10 integer from 1 to 365 (no sign, exponent,
spaces or non-ASCII digits). Anything else stops with an error; it never
falls back to a default silently.

```sh
sh install/linux/install.sh --channel stable --stable-days 14
FAMILIA_CHANNEL=stable python3 scripts/channel.py show
python3 scripts/channel.py resolve llama.cpp --channel stable --days 30
```

## What follows the channel

| Dependency | Source | On `stable` |
|---|---|---|
| llama.cpp runtime (`install/linux/install.sh`) | GitHub releases of ggml-org/llama.cpp | Upstream flags every `bNNNN` build as a prerelease and publishes `vX.Y.Z` releases as its stable line. Each carries `nightly-tag.txt`, naming the `bNNNN` build it was cut from. The heuristic runs over the `vX.Y.Z` releases and installs that build. `--build` still overrides. |
| hermes-agent | GitHub releases of NousResearch/hermes-agent | Exposed through `channel.resolve("hermes-agent")` for the Hermes wiring to call. |
| Hugging Face model files (`scripts/hf_fetch.py`) | the repo's commit history | When no revision is given, the most stable commit in the window replaces `main`. An explicit revision always wins. |
| Any GitHub project | `github:OWNER/REPO` | Same heuristic over its releases. |

Not covered yet: the parts in `pins.txt` (synced to their pinned commits by
`scripts/sync_pins.py`), the Termux and Windows installers, and the llama.cpp
pin in code-bootstraps-llama.cpp.

## How "most stable" is chosen

1. **Candidates.** Drafts and releases flagged as prereleases are dropped,
   along with tags that look like one (`rc`, `alpha`, `beta`, `pre`,
   `preview`, `dev`, `nightly`, `snapshot`). Any tag or revision that fails the
   strict name check is dropped too and logged, never used.
2. **Soak time.** For the newest candidate, soak time is the time since it
   was published. For an older one, it is how long it stayed un-superseded,
   until the next candidate was published. A candidate qualifies once it has
   soaked at least 24 hours.
3. **Pick.** Within the last N days, the newest qualifying candidate wins.
   The channel leans newer: anything that survived a day without being
   replaced is preferred over older releases.
4. **Fallback.** If nothing in the window qualifies, or the window is empty,
   the newest qualifying candidate from before the window is used. Last
   resorts are the newest candidate before the window, then the newest in the
   window. Every fallback is logged.

Releases deleted (yanked) upstream no longer appear in the list, so they are
never picked.

## API

```python
import channel  # scripts/channel.py
ref = channel.resolve("hermes-agent", channel=None, days=None)   # -> ResolvedRef
ref.ref, ref.kind, ref.release, ref.published_at, ref.fallback, ref.reason
```

`resolve(source_id, channel=None, days=None, *, now=None, fetch=None,
fetch_text=None, asset_re=None, environ=None)` returns a frozen `ResolvedRef`
with these fields: `source`, `channel`, `days`, `ref`, `kind` (`tag` or
`commit`), `published_at`, `fallback`, `reason` and `release`. `release` is
the upstream release that `ref` came from; it differs from `ref` only for
llama.cpp. On invalid input, `resolve` raises `ChannelError`. When nothing
can be resolved, it raises `ResolveError`.

The CLI prints only the validated ref on stdout, or JSON with `--json`, and
writes reasons to stderr. Exit codes: 0 resolved, 1 nothing resolvable or a
network error, 2 invalid input.

## Safety

- Names are never put into shell strings or `eval`. The channel, N, and
  fetched tag or revision names are validated against strict patterns
  before use.
- URL path segments go through `urllib.parse.quote`, and only HTTPS GETs
  are made. If `GITHUB_TOKEN` or `GH_TOKEN` is set, it goes only to the GitHub
  API host and is never logged.
- Each CLI resolution is recorded in
  `$XDG_STATE_HOME/familia/channel/<source>.json` (default
  `$HOME/.local/state/familia/channel`). The directory is created 0700 and must be
  owned by you. Each run writes through one private `tempfile.mkdtemp` in that
  directory, then renames atomically. Nothing is written to the system temp
  directory.
- No listeners.
