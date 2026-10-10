<!-- DRAFT — not published. Placeholders (<VERSION>, <DATE>, <RELEASE_URL>) must be filled and every item confirmed merged before release. -->

<!--
Draft release announcement. Placeholders: <VERSION>, <DATE>, <RELEASE_URL>.
Before publishing, confirm every item under "What's in <VERSION>" actually merged (#14–#19),
and pick ONE of the two "configuration graph" paragraphs below depending on whether it ships in this release.
-->

# familia <VERSION>: your models, your machines, one graph

*<DATE> · Brian Fundakowski Feldman*

This is the first real release of **familia**.

familia is a small top-level project that turns the local AI pieces I already run into one system I can reason about. That means llama.cpp model servers, the green-roomz alias gateway, the green-agentz fleet, and agents like hermes-agent, on a laptop, a desktop, and a couple of phones. It doesn't replace any of them, and it isn't a new model. It pins each piece at a known revision, checks them out side by side, and connects them as a graph you control.

The idea underneath it is old and good. In Julian Elischer and Archie Cobbs' NETGRAPH, nodes have named hooks, hooks connect in pairs, and data moves along edges while control messages can reach any node. familia uses the same split for models and agents.

## The one rule

**Your models and data stay on your machines. Nothing moves across a boundary unless you said so.**

Everything else follows from that rule:

- **You own every edge.** An environment variable, a flag, or a saved setting always wins. familia may *suggest* a connection, but it never opens one on its own.
- **Moves are declared.** A model file, a context, or a tool result moves along an edge as a declared transaction (`begin`, `commit`, `rollback`). It is never a hidden copy. When something has already left the machine, rollback says so instead of pretending.
- **`/remote` is an advisor, not an executor.** It never receives your local tools or API keys.
- **Least privilege.** Everything runs as your user. There are no `NOPASSWD` sudo rules.

## Two clicks

```sh
curl -fsSL https://raw.githubusercontent.com/brianreborn/familia/main/install.sh | sh
```

The first click runs the command. The second is a one-word acknowledgement of a voluntary contribution notice. Paying is never required. Then open `http://127.0.0.1:9931/?model=chat`, paste the API key from your terminal, and you're talking to `chat`. Code tasks hand off to `coder`, and a small resident `route` model dispatches between them.

Linux is the tested platform. Termux on Android runs the server and now keeps it alive in the background, using tmux, screen, or nohup plus a wake lock. macOS should work through the same installer but is untested. Windows doesn't have a top-level installer yet. I'd rather say that plainly than ship instructions that 404.

## What's in <VERSION>

- **The rename is finished.** The project was "feeldznutts" while it was a sketch. Installer URLs, install paths, and log messages now all say familia. (#12, #13, #16)
- **Docs that match the code.** Every install command points at this repository. Windows instructions that referenced files we don't ship are gone until a Windows installer exists. (#17)
- **Android fixes.** `android_start.sh` parses again (#14). Device host, port, and user come from your environment instead of being hard-coded, and host keys are no longer ignored (#18). Missing fleet helpers are <added | guarded — TBD> (#15).
- **Termux survival.** The server detaches and holds a wake lock so Android doesn't kill it mid-inference. (#7)
- **Engine coexistence.** Alternative llama.cpp builds are named `<executable>__<author>__<branch>` and isolated per build, so an experimental fork can't clobber the default one. (#10)
- **hermes-agent guidance.** Running hermes-agent against `coder` with compaction off could loop on HTTP 400 once a session outgrew the 16k slot. The fix and recommended settings are in the docs. (#19)

## Next: configuration you declare, not configuration that guesses

<!-- Option A: if it ships in <VERSION>, replace this section's first paragraph with: -->
<!-- "<VERSION> introduces the configuration graph (preview)." -->

Most local AI setups, mine included, configure themselves by guessing. They pick a RAM profile, turn on a route when a file shows up, and use whatever context size looks like it fits. When the guess is wrong, you find out later and somewhere else. The hermes-agent overflow above is exactly that kind of failure.

familia is moving to an **explicit, declarative graph** of models and agents. You declare which model serves which route on which machine, with what context, and which agents call it. familia measures the hardware and checks the declaration against it. It doesn't silently pick a different model, and it doesn't inflate context because some RAM happens to be free. A mismatch stops the start with an error that names the node, the declared value, and the measured value. The graph can still change at runtime, but every change is validated before it takes effect.

The design is still being worked out. The draft is in [`docs/configuration-graph.md`](https://github.com/brianreborn/familia/blob/main/docs/configuration-graph.md), and feedback is welcome in the issues.

## The pieces

| Project | What it does |
|---|---|
| [code-bootstraps-llama.cpp](https://github.com/brianreborn/code-bootstraps-llama.cpp) | Model server, fetch/verify, `/local` and `/remote`, installers |
| [green-roomz](https://github.com/brianreborn/green-roomz) | Alias gateway: one stable name per backend |
| [green-agentz](https://github.com/brianreborn/green-agentz) | Agent fleet |
| [Agent-Reach](https://github.com/Panniantong/Agent-Reach) | Reach tools, pinned and not vendored |

## Thanks and license

familia is under the Light-ware License, which is 4-clause BSD plus an invitation (not a condition) to help with rent, groceries, or keeping the lights on. Sub-projects keep their own licenses.

Release notes: <RELEASE_URL> · Issues: https://github.com/brianreborn/familia/issues
