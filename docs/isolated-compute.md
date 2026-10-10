# Isolated compute (`isolated_remote`) — design draft

Status: design only. Nothing here is implemented.

## The trigger: `ssh chat.hf.co`

Checked 2026-10-09:

- Service: Hugging Face's SSH chat entry point, reached with `ssh chat.hf.co`.
  Announced around 2026-10-08/09 (Reddit; Clem Delangue on X: "no config. no key.
  nothing — chat with open models, zero setup"). The t.co link in the reposted
  post (x.com/BlockInsight214/status/2108400320204386435, reposted by
  @BrianReborn_alt) resolves to https://chat.hf.co/.
- What it is: a terminal chat front end to models served by **HF Inference
  Providers** (e.g. Qwen3.8-27B; one user reports 127 models after logging in
  with a free account, another reports Kimi K3 after setting an SSH key).
- Auth: anonymous works. Signing in to an HF account / adding an SSH key unlocks
  more models (user reports; mechanism TBD).
- Official docs page: TBD (none found; chat.hf.co returned 504 to our fetch,
  and the box network could not reach port 22).
- Pricing / limits: posts claim free and "unlimited"; official quota TBD.
  Inference Providers is normally billed by usage, so expect limits.
- Hardware: not chosen by the user; provider-side. TBD.
- Isolation: the user gets a chat session, not a shell. Nothing persists locally
  and no tools run on your machine. Server-side logging/retention: TBD.
- Session lifetime: TBD.

**Important:** this is *not* rented isolated compute. It's chat inference over
SSH. You can't ship model weights, a GGUF, or a KV cache to it. It only takes
prompts in and returns text.

## How familia can use it

Add one host/runtime type, `isolated_remote`:

| field | meaning |
|---|---|
| `transport: ssh` | endpoint, e.g. `chat.hf.co` |
| `auth` | `anonymous` or `ssh_key` (key path, never stored in the graph) |
| `models` | remote model ids it may route to; must be listed explicitly, never auto-picked |
| `persistence: none` | validator rejects store/room attachments to this node |
| `accepts` | `prompt` only (for chat.hf.co); `model`, `kv` reserved for future providers that rent real compute |
| `ctx` | declared per model; agent window must equal it (same rule as local nodes) |
| `trust` | `external` — no secrets, no private repo content in prompts |

Validator rules:
1. Agents bound to an `isolated_remote` node can't have tools that need
   local state (store, reach, filesystem).
2. `accepts` must cover each edge type (a C2C/KV edge to chat.hf.co is rejected).
3. Its non-interactive scripting interface is TBD. Until it is verified, mark
   the node `interactive_only: true` and exclude it from automated routing.

## Open items (TBD)
- Official docs, terms, quotas, data retention.
- Whether a non-PTY (`ssh chat.hf.co "<prompt>"`) mode exists.
- A real isolated-compute provider (e.g. HF Jobs / Spaces with SSH) for `accepts: model|kv`.
