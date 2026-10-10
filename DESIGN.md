# FAMILIA

Federated Agents Mesh for Intelligent Local Interoperable Autonomy.

This is the super-project that makes the existing systems one topology. It does not replace them, and it does not claim a new model. A user of llama.cpp, green-roomz, green-agentz, or green-agency should recognize the top level as their own system with the other pieces attached, not as a foreign shell.

## What it is

A graph. Nodes have named hooks. Hooks connect in pairs. Data moves along an edge. Control is addressed at a node and does not have to follow the edge. That split is Julian Elischer and Archie Cobbs' NETGRAPH: the data plane is the graph, the control plane is a message you can send to any node while data keeps moving.

The user is in control of every edge. The system fills only the hooks the user left open. An explicit environment variable, a command-line parameter, and a saved panel value already follow that rule. FAMILIA keeps it for zones, transports, and agents.

"Teleport" means a declared move of one object along one edge: a model file, a context, a room, a brief, or a tool result. It is not a hidden copy.

## Super-project

One development tree. Each major project is a subdirectory checkout, left intact:

- `code-bootstraps-llama.cpp` — local router, models, `/remote`, installers
- `green-roomz` — alias gateway: one name, one backend, handoff back to the nexus
- `green-agentz` — agents, green-brainz, green-fleetz (the swarm), green-zkillz
- `green-agency` — the agency skill pipeline (probe, cache, snapshot, deploy)

The top directory is only the graph: node types, the transaction block, `/local`, `/remote`, and the two-click installer. It pulls a piece by naming a hook, not by copying source into a neighbor. green-fleetz stays the swarm until it has a reason to be its own checkout.

## Route names

A name a person or an agent types is one English word for the job. `coder` stays. No vendor, no parameter count, no `-agent`, no `-speculator`. The directory `models/<name>/` is that same word. A GGUF filename and a draft model are not route names.

| Was | Route |
|---|---|
| general, general-text-speculator | `chat` |
| coder, qwenstral-code-speculator | `coder` |
| decision, tool-router-agent | `route` |
| language | `translate` |
| vision-layout-agent | `vision` |
| audio-transcription-agent | `transcribe` |
| speech-synthesis-agent | `speak` |
| image-generation-agent | `draw` |
| semantic-embedding-agent | `embed` |
| retrieval-rerank-agent | `rerank` |
| safety-policy-agent | `safety` |
| security-monitor-agent | `guard` |

Lift is not a route name. It is one way to run `chat`: an outside agent that calls models. The speculative drafts stay inside `chat` and `coder`. They are not aliases a user picks.

Old names work as hidden aliases for one release, then they are rejected. The panel, the preset sections, and `HANDOFF` `suggest` use only the route column.

The launcher opens `chat`. `coder` is a handoff from `chat` or `route`, not the front door. The Linux preset keeps the section names `general`, `decision`, and `language`, and publishes `chat`, `route`, and `translate` as aliases.

## Nodes

| Node | What it is | Default hooks |
|---|---|---|
| model | one route name (`chat`, `coder`, `route`, `translate`, …) | `in`, `weights`, `kv` |
| agent | a green-agentz profile (`scripts/agent.py` is planned, not in the tree yet) | `task`, `tools`, `local`, `remote` |
| agency | one green-agency skill run | `in`, `out`, `snap` |
| room | one green-roomz alias (a named backend) | `in`, `handoff` |
| swarm | one green-fleetz member | `task`, `result` |
| store | a coherent snapshot of bytes | `read`, `write` |
| reach | Agent-Reach tools | `query`, `result` |

A hook that is not connected is closed. Data does not leak across a closed hook.

## Transaction block

Every move is one block, whether a person typed it or an agent emitted it. Same fields either way:

```
tx {
  id
  src          # node.hook
  dst          # node.hook
  object       # model | context | room | brief | file | tool
  key          # see transports
  limit        # tokens, bytes, or once
  snap         # snapshot the reader must use
  elect        # on only if the user turned this edge on
}
```

`/remote` and `/local` are the human spellings of this block. They nest. A child is a savepoint of its parent.

```
/local begin
  /remote begin
  /remote commit
/local rollback
```

Subcommands on both, and the same words as agent tools: `begin`, `commit`, `rollback`, `status`, plus `on`, `off`, `login`, `session`, `ask`, `take`, `zone`, `hook`, `snap`, and `send`. A model does not get a second syntax. The approval gate that already guards shell and MCP still guards these.

`begin` names the snap the tx reads. `commit` publishes that tx's declared writes to its parent. A nested commit is not durable until the outermost commit. `rollback` drops the uncommitted writes of that tx and its uncommitted children.

This is an ordinary distributed transaction. It does not rewind the machine.

- Atomicity covers declared local writes still inside the tx. It does not restore the pool or unrelated files.
- Isolation is snapshot isolation for those writes. Outsiders see the last committed snap.
- Durability starts at the outermost `commit`, when the new snap name is recorded.
- A remote reply, a torrent announce, an ssh write, or a tool that already ran cannot be unspoken. `rollback` compensates the local record only. `status` says `heuristic` when part of the tx escaped.
- Nesting does not multiply the `/remote` brief, and it does not turn the advisor into an executor.

`/remote` stays an advisor. It does not receive the local API key, it does not run local tools, and the brief stays under the existing caps (`BRIEF_MAX` 1600, prior reply 400, `max_tokens` 384). Auto stays off until `/remote on`.

`/local` is the same shape for what is already on this machine. It runs another terminal UI inside a model, an agent, or an agency: grok, agy, claude, codex, or `exec`. Start versus resume stays the rule already shipped. Empty session means start. A stored id means resume. Image, audio, video, and pdf stay paths, not bytes. `/local` is how a coding agent opens a second TUI without the user leaving the graph.

## Transports

The `key` names the object. The edge names how it moves. The user picks the edge. Autoconfig may suggest one and must not open it.

- Local path. The portable default. Works with no ZFS, no Docker, and no GPU.
- SSH. A host and a path. The control message can ride the same session. Data is the file.
- NFS, version 3 and version 4. A zone can be an export. v3 stays in the design because it is not a second client: the kernel mounts it, and we use the directory. We do not implement NLM, and we do not teach v3 the commit lock.
  - v3 is the byte path. Old machines already speak it. It holds a finished snap, a model file, or a saved KV file. Close-to-open is the rule: the writer closes the file, then another zone opens it.
  - v4 is the stateful path, and v4.1 when the server has sessions. One port, lease locks, delegations, and the commit record live here. A `begin` takes a v4 lock on the snap name. A `commit` publishes the new name. When the server is only v3, the commit record stays on a local file and the export is just the bytes.
  - The live KV pool stays in RAM. NFS stores the slot dump after step 1 of a virtual snapshot. Two routers do not mmap one KV file. A reader mounts the snap, or is given the path, only after the writer has closed it.
- rsync. The delta when both ends already have most of the bytes. The virtual snap area may itself be an NFS directory, so the rsync destination is `nfs://host/snap/<name>/` and the slot dumps go there with the tree.
- BitTorrent, including trackers. From [@born_brian85001](https://x.com/born_brian85001/status/2092741499587023105): the primary key is a magnet URI plus the path inside that torrent. Trackers are part of the design, not an optional extra. Re-optimizing a huge token repository is an offline command, one sub-agent per repository. GitHub files in that same thread use a diff delta plus a git revision, hashed locally.
- ZFS send of a named snapshot, when the pool exists. This is the strong form of the same idea, not a requirement for the first install.

Git, a torrent, rsync, and ssh are stores. They are not models. A model node loads weights from a store node. It does not speak the tracker protocol itself.

## Least privilege

The process uid is the user, including during the privileged step, wherever the operating system allows it. Becoming root is the last resort.

1. Do the work as the user with no extra right. `kill -STOP` and `kill -CONT` are this case: only processes this user started.
2. Escalate that same user. The uid does not change. Linux file capabilities on a tiny helper (`CAP_IPC_LOCK` for memlock, and `CAP_SYS_ADMIN` only for the one ioctl that needs it). ZFS delegated `zfs allow` so this user can snapshot that dataset. An fstab `user` mount so this user can mount the NFS export. A per-user memlock limit. The helper runs as the user, uses the one right, and that right is gone when it exits.
3. A root helper only when the kernel refuses step 2. One action, then drop before `exec`. No `NOPASSWD` sudoers entry. No helper that runs a general command. Files it creates are chowned to the user before it exits.

The agent, the router, `/local`, `/remote`, and every tool stay on step 1. They never hold a capability set or another login's key. v4 locks are taken as the user. Snap directories are mode 700. Key files stay mode 600.

Windows uses the same order. `SeLockMemoryPrivilege` is granted to the user for the one raise, and the process does not remain an administrator. Android is not rooted. A rooted phone still uses step 2 and then drops.

## Detached daemon mode and session persistence

On Android / Termux and remote machines, interactive terminal shells can be closed or reclaimed by the OS. Processes can run detached:

- `DETACH_MODE` option (`foreground`, `nohup`, `tmux`, `screen`).
- In `tmux` or `screen` mode, `start.sh` allocates a named detached session (`familia-server`).
- In `nohup` mode, file descriptors are detached from the controlling TTY, streaming stdout/stderr to `.cache/server.log`.
- On Termux, `termux-wake-lock` is held unconditionally so the daemon remains scheduled when backgrounded or detached.

## License

Code we write uses the existing Light-ware License, copied from `japanglify/LICENSE`. It is the 4-clause BSD license plus one addition. The four clauses are the copyright notice, the binary notice, the advertising acknowledgement ("This product includes software developed by Brian Fundakowski Feldman."), and the no-endorsement clause. The addition asks for a contribution toward rent, groceries, or keeping the lights on. That ask is an invitation, not a condition. Declining it does not change the four rights.

The two-click installer shows that invitation. It does not add a fifth legal term, and it does not block use on a refusal to pay.

Checkouts keep their own licenses. We do not relicense them. We do not copy a file whose terms are stricter than Light-ware into this tree. Lift's weights are modified OpenRAIL-M, so they stay outside. GPL-only code stays outside. Calling an agent is not vendoring it.

## Green-roomz on this llama.cpp

Green-roomz stays a checkout. Its design is the alias map and the handoff rule. Residency stays in green-roomz (its `scripts/serve.sh`), not in familia.

- A stable alias points at one backend. The manifest is the node declaration.
- `route` is the resident nexus. It is the small CPU model loaded at start, and it is moved aside only while another model is actually running. The old section name `decision` is not the route name.
- A specialist's first line may be `HANDOFF {"reason","suggest"}`, and then it stops. It does not answer as some other alias. Regex over the transcript is not the router.
- Benchmarks are cached by host fingerprint, runtime, manifest digest, and artifact identity. A new fingerprint requalifies. They do not run on every request.
- Engines that are not llama.cpp stay adapters behind the same alias. Whisper, Piper, stable-diffusion.cpp, and an Android sidecar do not become fake GGUFs.

## Engine co-existence: multiple llama.cpp branches and Ollama

Cutting-edge models often require forks or experimental branches of `llama.cpp` (custom model architectures, draft speculators, community PRs before upstream merge) or alternative local inference runtimes such as Ollama. These must co-exist on the same host without naming collisions, shared-library (`.so` / `.dll`) clobbering, or ambiguous dispatch.

- **Namespacing convention**: Executables and backend targets are disambiguated using the double-underscore suffix scheme:
  ```
  <executable>__<authorName>__<branchName>
  ```
  For example:
  - `llama-server__ggerganov__master`
  - `llama-server__ikawrakow__new-quant`
  - `llama-cli__brianreborn__android-mmap`
  - `ollama__ollama__main` (or an Ollama service adapter)

  Branch names containing slashes (e.g. `feature/moe-fix`) replace `/` with `-` (e.g. `feature-moe-fix`). The unadorned `llama-server` remains an alias or symlink to the default reference build.

- **Shared library and runtime isolation**: `llama-server` depends on dynamic libraries (`libllama.so`, `libggml.so`, `libggml-cpu-*.so`, Vulkan/CUDA backends) whose ABIs differ across forks and commits. To avoid cross-branch symbol pollution, each build tree resides in its own isolated directory:
  ```
  bin/llama__<authorName>__<branchName>/
  ```
  The suffixed executable in `bin/` (e.g. `llama-server__<authorName>__<branchName>`) is either built with an `$ORIGIN` runtime library search path (`RPATH`) or launched via a wrapper script that sets the isolated `LD_LIBRARY_PATH` / `DYLD_LIBRARY_PATH` before exec.

- **Ollama integration**: Ollama runs either through its native binary (`ollama serve`, exposing its OpenAI-compatible `/v1` endpoint on loopback) or as a managed sidecar. In FAMILIA, it is registered as an engine adapter behind a standard route name.

- **Route names remain clean**: The end user, UI, and coding agents still address clean, single-word route names (`chat`, `coder`, `route`). The node manifest or preset specifies the exact engine backend (e.g., `engine = llama-server__ikawrakow__new-quant` or `engine = ollama`). The graph routes the call to the declared backend without leaking compiler or branch specifics into the user-facing interface.

### Branch Format Specification & DReX-DLM Runtime

To support cutting-edge architectures that have not yet reached upstream `llama.cpp`, runtime branches and models follow a standardized specification:

1. **Pins Declaration**:
   Runtime forks are declared in `pins.txt` alongside repositories:
   ```
   llama-server__<author>__<branch>	<branch-or-commit>	<git-origin-url>	runtime: <role-description>
   ```
2. **Preset & Model Mapping**:
   Model sections in `config/models-preset.ini` specify both the model GGUF (downloadable from Hugging Face) and the engine identifier:
   ```ini
   [chat]
   model  = models/chat/drex-dlm-Q8_0.gguf
   engine = llama-server__nace-ai__edlm
   hf-repo = nace-ai/drex-dlm-Q8_0
   ```
3. **Candidate Model — DReX-DLM (Diffusion Language Model)**:
   - **Upstream Project**: [nace-ai/drex-dlm](https://github.com/nace-ai/drex-dlm)
   - **Candidate Role**: Evaluated as a potential new default for `chat`.
   - **Model Weights**: `nace-ai/drex-dlm-Q8_0` on Hugging Face.
   - **Required Runtime**: [nace-ai/llama.cpp](https://github.com/nace-ai/llama.cpp) branch `edlm`.
   - **Engine Identifier**: `llama-server__nace-ai__edlm`
   - **Execution & Invalidation**: DReX-DLM uses iterative discrete diffusion denoising rather than autoregressive causal token generation. Its execution states cannot share or restore KV cache slots from standard autoregressive models. When switching between DLM and autoregressive engines, slot states are marked engine-incompatible and re-initialized.

4. **Candidate Model — GEV-26B-Decide (Decision / Router)**:
   - **Upstream Project**: [autotrust/GEV-26B-Decide](https://huggingface.co/autotrust/GEV-26B-Decide) on Hugging Face.
   - **Candidate Role**: `route`. This is a 26B-parameter decision/tool-routing model from Autotrust, intended to replace or augment the existing small resident router. At 26B it will not fit on lowram or moderate profiles without GPU offload — it is a candidate for `route` only when adequate VRAM or a split CPU/GPU load is available. The small CPU model remains the resident default for `route` when this model is absent.
   - **Model Weights**: `autotrust/GEV-26B-Decide` (download from Hugging Face; GGUF conversion or an available quant required).
   - **Engine**: Standard reference `llama-server` (no special branch required unless the architecture is unsupported upstream).
   - **Profile Constraint**: Do not activate as the `route` resident on lowram or moderate without explicit `RESIDENT=1 PROFILE=default` override and confirmed VRAM. The current small decision model stays the fallback.

5. **Candidate Model — embedding-gemma-2 (Semantic Embedding)**:
   - **Upstream Project**: [google/embedding-gemma-2](https://huggingface.co/google/embeddinggemma-2) on Hugging Face.
   - **Candidate Role**: `embed` — activates the `embed` route alias once the model file is on disk. No alias is published until that file exists (per the existing rule for specialist routes).
   - **Model Weights**: `google/embeddinggemma-2` (download from Hugging Face; GGUF quant required).
   - **Engine**: Standard reference `llama-server` with embedding mode (`--embeddings` flag). The model produces dense vector representations; it does not generate tokens. Its KV cache and slot semantics differ from generative models — slots are not persisted across requests and are not snapshotted as part of the normal virtual snapshot sequence.
   - **Isolation**: Embedding requests must not share a llama-server slot or context with generative routes. The `embed` role runs as a separate router child with its own slot allocation.

This router already has the slots. Lowram keeps two (`chat` and `coder`) and leaves `route` unpinned. Default and moderate keep `route` resident, so `--models-max` is `MODELS_MAX+1`. A handoff is a new request to that route name, not a second HTTP server. Per-request `chat_template_kwargs.enable_thinking` is how a turn thinks. The preset stays `reasoning=off` until the user asks. Tools stay in the tools container.

`sm11` mailbox assists stay an optional hook for that one old GPU. They are off unless `GRZ_SM11=1`. CPU fallback remains.

## Cache coherence is a snapshot

Do not invent a RAM coherence protocol. The coherence epoch is the name of a filesystem snapshot. A task reads that snapshot and never the live tree. A writer creates the next snapshot only after the new tree is complete. Readers of the old name do not observe a half-written cache.

This is already how the existing systems work:

- green-zkillz REQ-SYS-03: an immutable `.bak` before any write. REQ-SYS-04 and REQ-SYS-05: a short-circuit cache whose `global_state_hash` is the identity of that generation.
- `freebsd-mac-grok` and `max-headroom-grok`: `zfs snapshot -r` before the mutation. A pool checkpoint is opt-in because rewind discards later transactions.
- [@born_brian85001](https://x.com/born_brian85001/status/2104425666464927886): off-site, ledger-based ZFS duplication, encryption at rest, for SSDs that cannot erase. The ledger entry is the snapshot name, not a timestamp an agent can rewrite.
- The public note that matches this (not found as a retweet of either account): put the work on a machine that already has a ZFS snapshot of the cache, instead of copying the cache in on a cold start.

The snap name is the same on every machine. The driver is whatever that filesystem can do. We pick the first one that works.

| Where | Driver |
|---|---|
| ZFS (Linux or FreeBSD) | `zfs snapshot` of the dataset. Send that snapshot when the copy leaves the machine. |
| Linux btrfs | `btrfs subvolume snapshot` |
| Linux bcachefs | `bcachefs subvolume snapshot`, when the tool is there |
| Linux LVM thin (ext4 or XFS on a thin pool) | an LVM thin snapshot |
| FreeBSD UFS2 | `mksnap_ffs` |
| macOS APFS | `diskutil apfs createSnapshot`, or `cp -c` (clonefile) when the snap is only a tree |
| Android / Termux, and any disk with hardlinks but no snapshot ioctl | `cp -al` of the tree onto the same filesystem |
| Nothing of the above | a virtual snapshot, below |

A virtual snapshot is not an rsync of the workspace alone. The KV pool is RAM (`kv-unified`, `cache-ram` in `config/models-preset.ini`). `LLAMA_CACHE` is only a temp directory and does not hold those tokens. Stopping the process first would freeze the KV inside an unresponsive server, and the copy would miss it.

Order:

1. Ask llama-server to save every live slot. That write is the KV and the prompt cache for `chat`, `coder`, `route`, and `translate`. Save the other RAM stores the same way: a room benchmark cache, a session file, whatever a stopped process could not flush.
2. `kill -STOP` only the processes that can still change those files. The server is already flushed, so it is stopped too.
3. rsync into the virtual snap area: the workspace, `.cache` (except the snap area itself), the slot dumps, and the session record. That area may be a local directory or an NFS export. One snap name covers that set. The KV files are part of the set, not an afterthought.
4. `kill -CONT`.

The transaction reads that named set. It does not read the live tree or the live KV. Rollback throws away an uncommitted snap. It does not restore the machine, and it cannot pull back a reply that already left.

- **Cross-branch and cross-engine memory isolation**: In-memory state, session context, and KV slot dumps are strictly bound to the exact engine binary, branch, and build identity that created them. Memory cannot be swapped or restored across different branches of `llama.cpp` or between `llama.cpp` and `Ollama`, because internal tensor layouts, tokenizer mappings, context structures, or quantization layers may have changed. A snapshot metadata record includes the engine tag (`<engine>__<author>__<branch>`); if a transaction or snapshot is read by a different branch or runtime, only cold filesystem state (workspace files, configs, and transcripts) can be transferred—the in-memory KV cache must be safely invalidated and recomputed rather than restored.

[@BrianReborn_alt](https://x.com/BrianReborn_alt/status/2106354991133016574) asked the right test: a utilization number is not a win until useful work is separated from cache thrash. The first measure is bytes read from the named snapshot versus bytes rewritten because the snapshot was missing.

## What the retweeted papers change, and what they do not

Searched [@BrianReborn_alt](https://x.com/BrianReborn_alt) and [@born_brian85001](https://x.com/born_brian85001), including native retweets.

- Memory Attention (alphaXiv, quoted by BrianReborn_alt on 25 Sep 2026): reuse a stored value instead of recomputing it, and let that store sit off the GPU. That is the snapshot store, not a new attention layer. A reply on that post said the released model and the measured offload path were not the same code. Do not vendor it.
- Looped Diffusion Transformer, Matryoshka Attribution, and the Tsinghua shortest-path note were retweeted. They are references for reuse and for graph cost. They are not node types.
- No retweet on either account was a MESI or directory-protocol paper. Coherence in this design is the snapshot rule above, plus the ZFS posts, not a hardware protocol ported into Python.

## Posts under review

More posts are still coming. Each one is added here before it becomes a node.

### Lift (datalab-to/lift)

From [@akshay_pachaar](https://x.com/akshay_pachaar/status/2106361169690956041). [datalab-to/lift](https://github.com/datalab-to/lift) is a general model, not an extract-only role and not a GGUF. The program we run is an agent that calls models: `lift_extract` routes to a vLLM server or a Hugging Face backend (`VLLM_API_BASE`, `--method hf|vllm`). We do not convert it, host its weights, or give it a llama-server slot.

In the graph it is one implementation of `chat`. A document is still a `path=` (`pdf` or `image`). A JSON schema is one thing that general agent can be asked to fill, including a transaction block, with nulls where the page is blank. Datalab's own numbers, for that schema task only: 90.2% field accuracy, 20.9% full-document accuracy, median 9.5s. A person confirms a tx built from a document before it commits. Code is Apache-2.0. Weights are modified OpenRAIL-M and stay outside this tree. Marker, surya, and chandra are not part of this commitment.

## Agent-Reach

[Agent-Reach](https://github.com/Panniantong/Agent-Reach/tree/main) is the reach node: web and other non-distribution tools. It is not the distribution system, and it is not pasted into llama-server. Pin a commit. Its tools enter through the existing approval gate. `/local`, `/remote`, ssh, rsync, and BitTorrent stay the distribution tools.

## Two clicks, old and new

A platform is not supported until the same two clicks install it on an old device and a current one.

The first click is the install command: `curl | sh` or `irm | iex`. The Windows script stays PowerShell 5.1. The unpacked tree must run with no ZFS, no GPU, and no new runtime. `VARIANT=cpu` and file snapshots are that path. ZFS, Vulkan, NFS, and a tracker are upgrades the graph offers when the hooks exist.

The second click is the donation-ware tap-through. A terminal asks for one word. A phone asks for one tap. The install does not continue until that answer. Paying is not required, and the notice cannot be skipped. There is no third question.

The installer records a digest when one is published and still installs when it is empty, which is the current `install.sh` behavior (no Windows installer is shipped yet). The super-project installer checks out the four subdirectories at pinned revisions. It does not ask the user to assemble them.

## First build, after this plan

The GitHub repository is created only after this plan is accepted. Nothing is committed before that review.

1. Top-level tree and pins. No code moved between projects. Our `LICENSE` is the Light-ware License from `japanglify/LICENSE`.
2. The transaction block, parsed by the agent, stored next to `remote.json`.
3. `/local` as a peer of `/remote` in the planned `scripts/agent.py`, same subcommands, in the tool list.
4. Snapshot-before-write. Use the filesystem driver when one exists. Otherwise dump slot KV first, `kill -STOP`, rsync the tree plus those dumps, then `kill -CONT`. The launcher opens `chat`.
5. Two-click install of that tree on this Linux host and a documented PS 5.1 path. The second click is the donation-ware tap-through. Do not block on a live Windows run.

Leave BitTorrent, trackers, rsync, and ssh as node types with no protocol code until the block and `/local` are real. A transport that cannot name a snapshot is not allowed to feed a model.

## Visual Graph Configuration

The configuration UI must support interactive topology design. This means providing the ability to visually set up components in a netgraph style, allowing users to configure both small, straightforward neural networks and easily manage larger, federated systems spanning multiple hosts. Alternatively, the UI must support configuring the system through a natural language description of the desired setup.

## Documentation Requirements

Serious, comprehensive documentation is a mandatory requirement for this project. There must be a dedicated, real Markdown manual (`MANUAL.md` or similar) that covers:

1. Installation and initial setup
2. Administrative tasks and configuration management
3. End-user usage and examples

The documentation must serve as a practical guide for using the software in production, moving beyond merely describing implementation details or architecture.
