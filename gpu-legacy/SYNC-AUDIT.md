# sm11 sync / lock audit (qodesh, GeForce 8600 GT, sm_11, WDDM)

Rule: no host sync per op. Each token's forward is enqueued asynchronously on the one CUDA
stream. The host waits at most once per token, and that wait is an event poll
(`cuEventQuery` + `SwitchToThread`), not `cuCtxSynchronize`. Nothing in the hot path takes a mutex.

## Primitives (sm11_shim.c)
- `async_init`: 1 MiB pinned staging (`cuMemHostAlloc`) plus one event. `SM11_SYNC=1` brings back the old blocking path for A/B runs.
- `sm11_htod`: memcpy into pinned staging, then `cuMemcpyHtoDAsync`. Doesn't wait.
- `sm11_dtoh_many` / `sm11_dtoh_wait`: async D2H of every result into pinned memory, then one `sm11_fence` (event record + poll), then memcpy out.
- Mapped/zero-copy memory isn't used yet: I haven't verified `canMapHostMemory` on G84 (driver 342.x). Pinned memory plus async DMA works and is portable.

## Audit, site by site
| site | before | after | justification if kept |
|---|---|---|---|
| `sm11_matmul` (F32 per-op hook) | ctx sync + blocking D2H | async H2D/D2H, 1 event poll | ggml-cpu reads the result straight away, so one wait per op is inherent to a per-op hook |
| `sm11_q4_matmul` / `sm11_q8_matmul` | ctx sync + blocking D2H | async, 1 event poll | same as above |
| `sm11_wmatvec` (ggml hook, resident W) | blocking D2H (implicit sync) | async, 1 event poll | same as above |
| `sm11_matvec_batch` | ctx sync + N blocking D2H | N async D2H + **one** event poll | — |
| stories15M `sm11_forward`, GPU cls | ctx sync + blocking D2H | async D2H + 1 event poll per token | the 1 wait per token is needed because greedy decoding of token N+1 depends on token N |
| stories15M `sm11_forward`, CPU cls (default) | ctx sync + blocking D2H x | 1 event poll per token | same as above |
| token / rope uploads in `sm11_forward` | blocking H2D | pinned async H2D | — |
| weight upload at register / `wc_get` | blocking H2D | **kept** | one-time load, not in the hot path |
| `bench_*`, `kbench` timing | ctx sync | **kept** | only used for measurement |
| locks | none found (no mutex / CriticalSection in shim, bridge, run.c, smol_sm11.c) | none | — |

The per-op ggml hook still waits once per op, and that can't be fixed inside the hook, because
ggml-cpu runs ops one after another on host buffers. The root fix is to skip the hook for the
decision model and run the whole forward pass on the device: `smol_sm11` (SmolLM2) and
`sm11_forward` (stories15M). Each enqueues about 600 launches per token and waits once.

## Lock-free CPU/GPU handoff (smol_sm11 `serve` mode)
- Two SPSC rings (`g_in`: caller → GPU worker, `g_out`: worker → caller). Only the producer writes `head` and only the consumer writes `tail`. Publication uses `MemoryBarrier` + `InterlockedExchange`. There are no mutexes and no kernel waits; both sides poll and yield the core.
- The GPU worker thread owns the CUDA context and keeps up to 2 requests in flight, each with its own KV cache and its own pinned result and event. While the GPU runs request A's token N, the host finishes request B's token (top-K rescoring, argmax, embedding of the next token) and enqueues it. That is the double-buffer. A single greedy stream can't overlap with itself, because token N+1 needs token N's argmax.
