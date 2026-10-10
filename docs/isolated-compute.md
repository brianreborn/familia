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
- Non-interactive use: verified 2026-10-09 from miryam: `ssh -T chat.hf.co` returns
  `Requires an active PTY`. Scripts must allocate a PTY (`ssh -tt chat.hf.co`, or
  drive it with expect/pexpect) and parse the TUI output.

**Important:** this is *not* rented isolated compute with a shell. It's a
remote chat session over SSH. Native inputs today are prompts (and text out).
Shipping weights or a KV cache as *native* accepts is TBD per provider; training
and KV work are still allowed via **upcalls** to trusted familia nodes (see
below).

## How familia can use it

Add one host/runtime type, `isolated_remote`:

| field | meaning |
|---|---|
| `transport: ssh` | endpoint, e.g. `chat.hf.co` |
| `auth` | `anonymous` or `ssh_key` (key path, never stored in the graph) |
| `models` | remote model ids it may route to; must be listed explicitly, never auto-picked |
| `persistence: none` | validator rejects store/room attachments to this node |
| `accepts` | native inputs: `prompt` for chat.hf.co today; `model`, `kv` reserved for providers that take them natively. Training/KV also via `upcalls` (below). |
| `ctx` | declared per model; agent window must equal it (same rule as local nodes) |
| `prefill_ratio` | optional float in `(0, 1)`; fraction of remote `ctx` to fill with primer before the real data (typical 0.5–0.6). Omit when unused. |
| `primer` | optional; source of primer/context material (`path`, `inline`, or `ref`). Required when `prefill_ratio` is set. Must pass the `trust: external` rule (no secrets / private content). |
| `upcalls` | required block: `allow` list (may be empty), plus `max_upcalls`, `timeout_s`, `max_payload_bytes`. Empty `allow` = no upcalls; no wildcards. |
| `trust` | `external` — no secrets, no private repo content in prompts (or upcall results, unless the graph explicitly allows) |

Validator rules:
1. Agents bound to an `isolated_remote` node can't have tools that need
   local state (store, reach, filesystem).
2. `accepts` must cover each edge type (a C2C/KV edge to chat.hf.co is rejected).
3. The service requires a PTY (no plain `ssh host "prompt"` mode). The node
   declares `requires_pty: true`; the runtime adapter must use `ssh -tt` or
   pexpect and strip TUI escapes. Until the adapter exists, exclude the node
   from automated routing.

## Schema example

```yaml
hosts:
  hf-chat:
    type: isolated_remote
    transport: ssh
    endpoint: chat.hf.co
    auth: anonymous          # or ssh_key (key path never stored in the graph)
    persistence: none
    requires_pty: true
    trust: external
    accepts: [prompt]        # native inputs; training/KV also via upcalls (below)
    models:
      - id: Qwen/Qwen3-27B   # example; must be listed explicitly
        ctx: 32768
    prefill_ratio: 0.55      # fill ~55% of ctx with primer before real data
    primer:
      source: path           # path | inline | ref
      path: primers/hf-chat-public.md
    upcalls:
      allow:                 # empty list = no upcalls; no wildcards
        - tool: train_step
          args_schema: schemas/train_step.json
          target: miryam-trainer   # must be a declared graph node
        - tool: kv_build
          args_schema: schemas/kv_build.json
          target: miryam-kv
      max_upcalls: 32
      timeout_s: 120
      max_payload_bytes: 1048576
```

Validator additions for prefill and upcalls:
1. If `prefill_ratio` is set, it must be in `(0, 1)` (exclusive).
2. `primer` is required whenever `prefill_ratio` is set; primer source must be declared.
3. Primer content must satisfy `trust: external` — no secrets, no private repo content
   (unless the graph explicitly allows a named exception — TBD).
4. Prefill tokens ≈ `floor(prefill_ratio * model.ctx)`; the remaining window must still
   fit the agent payload (same exact-window rule as local nodes).
5. `upcalls.allow` is required on every `isolated_remote` node (may be `[]`). Empty
   means no upcalls. No wildcards (`*`, `tool: any`, open targets).
6. Each allow entry needs `tool`, `args_schema`, and `target`; `target` must name a
   declared graph node.
7. Upcall results returned into the session also pass `trust: external` unless the
   graph explicitly allows otherwise.

## Upcalls

The remote session is a **general computer**: it may lack native local tools and
storage, but familia **permits upcalls**. The remote model emits structured
tool-call requests (e.g. JSON blocks on the PTY stream). A familia adapter:

1. Parses the request from the stream.
2. Checks it against the per-node `upcalls.allow` list in the graph (`tool` name,
   `args_schema`, `target` trusted node).
3. Executes the tool on that trusted node.
4. Returns the result into the remote session.

Limits (declared on the node, enforced by the adapter): `max_upcalls`,
`timeout_s`, `max_payload_bytes`. Every upcall is logged. Results returned to
the session also pass the `trust: external` rule (no secrets / private data
unless the graph explicitly allows). Provider-specific stream framing and
refusal behavior: TBD.

## Training / prefill use

Intent: use `isolated_remote` nodes for training-style workloads by filling the
session context (KV) to about **50–60%** with primer / context material before
processing the real data, and by driving heavier work through upcalls.

### In-session prefill

Pad the session with primer text up to a declared `prefill_ratio` (e.g. `0.5`–
`0.6`) of the remote model's declared `ctx`, then send the actual data in the
remaining window. This builds useful KV state inside the remote session before
the workload starts. Validator rules for `prefill_ratio` and `primer` are above.

### Training / KV via upcalls

Native tools on the remote side may be absent, but the model can still drive
training steps or KV-state construction by **upcalling compute on trusted
nodes** listed in `upcalls.allow` (e.g. `train_step` → `miryam-trainer`,
`kv_build` → `miryam-kv`). Combine that with in-session prefill at
`prefill_ratio` ~0.5–0.6.

Direct `accepts: model` / `accepts: kv` on the remote node itself remains
reserved for providers that natively accept those inputs. Until a provider is
verified, treat the following as TBD:

| claim | status |
|---|---|
| chat.hf.co (or similar) stream format for structured tool-call JSON | TBD |
| HF Jobs / Spaces SSH native load of our GGUF or transformers weights | TBD |
| Native remote KV-cache prefill or C2C-style injection (no upcall) | TBD |
| Ephemeral disk / no tools / no persistence guarantees per provider | TBD |
| Billing, quotas, data retention for training jobs | TBD |

## Open items (TBD)
- Official docs, terms, quotas, data retention.
- Stable output format for PTY scraping (TUI may change without notice).
- Structured upcall framing on chat.hf.co / other PTY chat UIs.
- A provider that natively accepts `model`/`kv` (e.g. HF Jobs / Spaces with SSH).
- Primer packing strategy (token count vs char estimate) for PTY chat UIs.
- Graph syntax for explicit trust exceptions on upcall results.

## Measured 2026-10-09 22:20 PT (qodesh, Windows 10, pywinpty)

| Item | Value |
|---|---|
| Auth | `ssh_key`: the qodesh ed25519 key is linked to HF. The banner shows `@BrianReborn`. |
| Default model | `Qwen/Qwen3.8-27B` (via Inference Providers; `/model` switches) |
| Reply | **None.** The provider returns `error: 402 Payment Required: You have no remaining credits. Purchase pre-paid credits...`. The service is not free for this account right now. |
| Session setup | about 6 s to the chat screen; the 402 comes back about 1 s after enter |
| context_tokens | TBD (needs a working reply; the adapter defaults to 32768 as a placeholder) |
| compaction_threshold | TBD (whether the service auto-compacts or truncates, and at what fill, is unmeasured) |
| Max single message | TBD |
| Rate limits | TBD (blocked by credits before any rate limit) |

## Limits: never let the remote compact

New node fields (see `scripts/isolated/hfchat.py`):

| Field | Meaning |
|---|---|
| `context_tokens` | remote model window (measured or from model docs; TBD here) |
| `compaction_threshold` | fill at which the service compacts or truncates; TBD defaults to `0.8 * context_tokens` |
| `safety_margin` | tokens kept free; default `max(512, context_tokens/20)` |
| `max_fill` | derived: `compaction_threshold - safety_margin` |

`prefill_ratio` now defaults to `max_fill / context_tokens`. Validator rule:
`prefill_ratio * context_tokens <= max_fill`. The adapter estimates tokens
per session (about 4 chars per token unless a tokenizer is supplied). When the
next turn would cross `max_fill`, it opens a new session that carries a compact
local summary instead of letting the remote compact.
Exit codes: 0 reply, 3 timeout, 5 provider refusal (402/auth/429).

## chat.hf.co model switching (measured 2026-10-09, qodesh, #36)

- `/model` opens a filterable picker (press enter on the splash screen first, then type `/model`, enter;
  type part of a name to filter, enter to select). On 2026-10-09 it listed 128 models, all served through
  Hugging Face Inference Providers (e.g. CohereLabs/tiny-aya-*, deepseek-ai/DeepSeek-R1-Distill-Qwen-7B,
  DeepSeek-V4-*, Qwen/Qwen3.8-27B default).
- Credits are per account, not per model: CohereLabs/tiny-aya-global and
  deepseek-ai/DeepSeek-R1-Distill-Qwen-7B both returned `402 Payment Required: no remaining credits`
  in about 6 s, the same as Qwen3.8-27B. No free model was found, so context window, latency and
  compaction behaviour remain **TBD** until the account has credits.
- Until measured, `hfchat.py` keeps `context_tokens=32768` as a placeholder with
  `compaction_threshold = 0.8 * context_tokens` and rotates sessions before that.

