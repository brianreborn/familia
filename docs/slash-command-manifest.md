# Slash-command manifest

**Status:** design and reference validation only. The example manifest is not a live command registry; menu, gateway, and harness adapters are follow-up work.

## Purpose

Each consumer may offer short slash aliases, but all commands have one stable canonical identity beginning with `familia-`. A consumer can omit or rename a short alias without changing the canonical name. Canonical commands remain resolvable for every consumer. This manifest defines names and dispatch targets; authorization and whether a handler is installed remain separate checks.

This is the shared command namespace for operator slash commands and route tokens. For example, `/begin` can dispatch to `familia-focus-begin`, while `/coder` can dispatch to `familia-route` with a fixed `route: coder` argument. The alias is presentation syntax; the canonical command is the operation. Graph-derived route aliases must be materialized for the consumer from that consumer's graph before help and unknown-token responses are generated.

The ordinary `familia` CLI and its existing `scripts/cli-commands.txt` / `scripts/menu-items.txt` catalog are a separate interface. They should adopt this manifest only through an explicit adapter; this design does not replace those catalogs or imply that every future slash command already has a handler. Likewise, hiding a name from help is not access control: canonical commands still resolve and authorization must be enforced by the command handler.

## Schema, version 1

The reference shape is in [`config/slash-command-manifest.example.json`](../config/slash-command-manifest.example.json). It is a synthetic example, not production configuration.

```json
{
  "schema_version": 1,
  "commands": [
    "familia-focus-begin",
    "familia-focus-await",
    "familia-focus-end",
    "familia-route"
  ],
  "consumers": {
    "gateway": {
      "aliases": [
        {"name": "begin", "command": "familia-focus-begin"},
        {"name": "coder", "command": "familia-route", "arguments": {"route": "coder"}}
      ],
      "help": ["begin", "await", "end", "coder"]
    },
    "minimal-client": {
      "aliases": [],
      "help": []
    }
  }
}
```

`commands` is the global set of canonical identifiers and is identical for all consumers. Each `consumers` entry contains:

- `aliases`: zero or more records mapping a one-token short name to a canonical command. Optional `arguments` are fixed JSON object values added by that alias, such as a graph route target.
- `help`: the ordered names this consumer exposes to users. Each item must be either a canonical command name or an alias registered for this consumer. The same list is used for help and the valid-token list in an unknown-command response.

Names in the data omit the leading `/`; the prompt adapter adds it when parsing or displaying slash syntax. Do not put display text, handler code, permission decisions, host data, or credentials in this file.

## Resolution and collision rules

1. Every canonical name in `commands` resolves in every consumer, including consumers with no aliases or no help entries.
2. A registered alias resolves only in its named consumer. Consumers may use different aliases for the same canonical command.
3. Alias names are single lowercase tokens. A leading slash is syntax, not part of the stored name.
4. Canonical names are unique and use the reserved `familia-` prefix. A short alias may not equal any canonical name or use that reserved prefix.
5. An alias name may appear only once within a consumer. Duplicate aliases are rejected even if they happen to map to the same command; this avoids order-dependent overrides.
6. Each alias target must name a declared canonical command. Unknown targets are rejected.
7. Each help entry must be registered for that consumer, and help entries may not repeat. Internal canonical names and aliases not listed in `help` are omitted from both help and the unknown-token list.
8. Unknown tokens fail closed. They do not fall through to a default route. The error may list only that consumer's `help` entries.
9. Name visibility does not grant permission. The resolved canonical command must perform normal authorization and capability checks.

## Consumers and integration boundary

The manifest is data. A single resolver validates it, resolves aliases to canonical invocations, and returns the exposed names. Consumers should not maintain separate hard-coded alias arrays or construct help/404 token lists independently.

`docs/config/routing-spec.md` now points CFG-SPEC-PLAN-007 and CFG-SPEC-GW-004 at this contract. In a later integration slice, each consumer adapter should:

1. load the validated manifest and its own graph-derived route entries;
2. resolve an incoming slash token to `{command, arguments}`;
3. pass the canonical invocation through existing authorization and dispatch;
4. use the same exposed-name function for help and unknown-token responses.

The current reference API lives in `scripts/slash_command_manifest.py`. This PR deliberately does not alter the green-roomz route parser, Familia menus, or an external harness. Those consumers have separate data and release boundaries; wire them to the shared contract in small follow-up issues so this design does not turn into a cross-project rewrite.

## Tests

`tests/test_slash_command_manifest.py` checks canonical resolution with no alias, per-consumer alias isolation, alias-to-canonical arguments, duplicate alias rejection, canonical-name collision rejection, and help/token listings restricted to explicitly exposed names.
