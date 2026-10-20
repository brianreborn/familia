# Topology bandwidth prototype (design)

Status: proposal, nothing built yet. Source material: a shared Grok
conversation, "GeForce 8600 Memory Bandwidth and Topology Speeds". Every number
taken from it is an **estimate to verify**, never an input to placement until
familia has measured it on the real machine.

## Goal

familia already decides which model server and agent run where. This design
gives that decision real numbers: familia measures the bandwidth and latency of
each link a token's data crosses (VRAM, PCIe each way, the copy engine, host
RAM, the LAN between hosts), keeps them as a per-host link model, and uses that
model to place model layers and agents. It targets roughly 15-year-old hardware,
where the gap between links is large (about 8:1 VRAM to PCIe on a G84) and a bad
placement costs more than the whole compute budget.

Out of scope for this prototype: the "TurboCache Plus" idea from the source
(host-side bus mastering into VRAM, BAR remapping, IOMMU-backed coherence).
It is kept below as a later research track. The prototype only measures and
places; it reprograms nothing.

## Estimates from the source (to verify)

| link | estimate | how familia checks it |
|---|---|---|
| G84 VRAM (128-bit GDDR3) | ~32 GB/s peak (8600 GTS figure; the GT has slower memory) | device-to-device copy and a streaming read kernel |
| PCIe 1.1 x16, each way | 4 GB/s theoretical, ~3-3.5 GB/s sustained | pinned H2D / D2H sweep |
| copy engine | one engine, half-duplex, no overlap with kernels | overlap test (below) |
| system memory reached by the GPU | PCIe-bound, same ceiling as DMA | mapped-memory read kernel, if `canMapHostMemory` holds |
| L2 | ~32-64 KB, unconfirmed | not needed for placement; skip |

## Architecture

Three pieces, each a small program or module:

1. **Probes** (`familia probe-links`, new). Microbenchmarks run on each host and
   write one JSON record per link: host role, device, driver branch, link name,
   direction, transfer size, bytes/s (median and p10/p90 of N reps), latency,
   and the raw command used. Records go into `registry/`, beside the existing
   bench records, so they are versioned and diffable.
2. **Link model.** A graph: nodes are memories (VRAM per GPU, host RAM per
   host), edges are links (PCIe H2D, PCIe D2H, LAN host-to-host), each with a
   measured bandwidth curve over transfer size, a fixed latency, and a
   `serializes_with` set. On the G84, H2D, D2H and kernel execution are all in
   one set, because the single copy engine and the compute engine never run at
   once. A missing measurement makes the edge "unknown", and the planner
   refuses to rely on it.
3. **Planner.** For one model (layer count, bytes per layer of weights, KV
   bytes per token, activation bytes per token) and one candidate placement,
   it estimates per-token time as the compute time per device plus, for every
   boundary the activations cross, `latency + bytes / bandwidth`, summed (not
   overlapped) inside any serialization set. Host syncs per token are counted
   separately, each charged a measured sync cost. The planner ranks placements
   (all-GPU, GPU layers 0..k plus CPU, split across hosts, agent beside its
   model or remote) and prints the predicted tok/s next to the measured tok/s
   whenever a run exists. Getting the prediction wrong is a result we record.

The placements become ordinary familia config (llama.cpp `-ngl`/tensor split,
which host runs which server and agent). The planner suggests; the user picks.

## What gets measured

All on a legacy-CUDA path that works on both target hosts (driver API, no
features newer than the card supports):

- **H2D / D2H, pinned and pageable.** bandwidthTest-style sweep, 4 KiB to
  64 MiB, powers of two, 20 reps each. Pageable shows the cost of the staging
  copy; pinned is the link ceiling.
- **Device-to-device copy and a streaming read kernel.** Gives effective VRAM
  bandwidth, compared with the ~32 GB/s estimate.
- **Copy/compute overlap test.** Time a kernel alone (K), a 32 MiB H2D alone
  (C), then both issued on two streams with async copy from pinned memory. If
  the combined time is close to K + C, there is no overlap; close to max(K, C)
  means overlap. Also issue H2D and D2H together to test duplex. Expected on
  G84: no overlap and no duplex. The test proves it or disproves it, and the
  result fills `serializes_with`.
- **Mapped (zero-copy) memory.** Check `canMapHostMemory`; if set, read
  host memory from a kernel and measure it. The existing sync audit notes this
  is still unverified.
- **Sync cost.** Round trip of an event record and poll, and of a context
  synchronize, on an idle stream.
- **Host RAM.** STREAM-style copy/triad on each host (single thread and all
  cores).
- **LAN.** TCP throughput and round trip between hosts (an iperf3-style test
  or a small built-in sender), plus the time to move one activation tensor of
  the planned model's size.
- **End to end.** Host syncs per token (instrumented counter in the shim; the
  earlier work brought it from 211 to 1 on the 8600 GT host) and tok/s for
  prefill and decode, for each placement the planner ranks top 3.

## Minimal first build

Small enough to finish and run on both target hosts:

1. `gpu-legacy/bench_links.c`: one C file on the CUDA driver API (works with
   the legacy branch on the 8600 GT host and the 340 driver on the CentOS 10
   host). It runs the H2D/D2H pinned+pageable sweep, the D2D copy, the overlap
   and duplex tests, and the sync-cost test, and prints JSON lines. Kernels come
   from the existing PTX the repo already loads for sm_11. Building against the
   340-era toolkit on CentOS 10 may need an older gcc or a container; that is
   the first thing to check.
2. `scripts/probe_links.py`: runs `bench_links`, a host-RAM test and an
   optional LAN test against a named peer role, then writes records into
   `registry/`.
3. `scripts/plan_placement.py`: reads the records and a model description,
   prints a ranked table of placements with predicted tok/s, and marks every
   edge it had to treat as unknown.
4. One validation run per host: run the top suggestion and the all-CPU
   baseline, record measured tok/s and syncs per token next to the prediction.

Done means: both hosts have link records, the overlap test has a recorded
verdict for the G84, and the planner's prediction for one small model is
within a factor we write down beforehand (start with 30%) of the measurement.

## Risks

- **Toolkit and driver age.** The 340 driver and the legacy branch need old
  toolkits; a modern distro may not build or load them. Mitigation: driver API
  only, prebuilt PTX, build in a container if needed.
- **Display and WDDM interference.** A GPU that also drives a display, or a
  Windows host with WDDM batching, distorts timings. Run probes with the
  display idle and record the OS and driver in every record.
- **The estimates are wrong.** The GTS figure is not the GT's; the PCIe
  generation and lane count the slot actually trained at may differ. Record
  the negotiated link (`lspci -vv` LnkSta or the OS equivalent).
- **Tiny models hide the links.** On very small models compute or launch
  overhead dominates and the model has nothing to say. Pick a test model large
  enough that transfers matter.
- **Planner overfits one machine.** Keep it a simple additive model and
  record misses rather than adding fudge factors.
- **Scope creep into TurboCache Plus.** BAR remapping, PRAMIN access and
  IOMMU work can hang or corrupt a machine. Not in this prototype.

## Later research track: TurboCache Plus

From the source: host-initiated writes into VRAM concurrent with GPU pulls,
an ownership directory (CPU / GPU / shared) kept in software and possibly
marked in IOMMU ignored PTE bits, and lock-free rings between the two sides.
Prior art named there (to verify before citing): GPU TLB reverse-engineering
via BAR0 PRAMIN, GPUDirect RDMA/Storage/P2P, user-space NVMe-to-GPU work,
Resizable BAR and an open UEFI ReBAR driver. Coherence would be by software
ownership, with the IOMMU at most carrying hints. It starts only after the
link model above shows where a faster host-to-VRAM path would pay off, and
only on a host whose loss would not matter.

## Layer streaming (AirLLM-style, #90)

`plan_placement.py` now has two streaming placements for models that do not fit:

- **layer-stream** (weights > free VRAM): each layer is copied host->VRAM once per token into
  one of two VRAM slots and read there. A layer that does not fit twice in VRAM is split into
  tensor-sized pieces (`units`). Per token: `max(bytes/pcie_h2d, 2*bytes/vram_copy) + units*20 us`
  (H2D on the copy engine overlaps the device read on the other stream).
- **disk-stream** (`--ram-budget` < model): the uncached part is re-read from disk each token at
  the measured `disk_read` rate.

`gpu-legacy/layer_stream.c` (driver API only, runs on 340.108; no kernels) measures the transport
bound of layer-stream; `scripts/perf/validate_layer_stream.sh LINKS MODEL...` compares it with
the planner. centos10-bigram, 8600 GT (233 MiB free), 2026-10-19, 3 tokens each:

| model file | units x MiB | predicted tok/s | measured tok/s | error |
|---|---|---|---|---|
| Qwen3.5-2B-Q4_K_M.gguf | 24 x 50.9 | 2.565 | 2.515 | +2.0% |
| Qwen3.5-9B-Q4_K_M.gguf | 64 x 84.65 | 0.579 | 0.570 | +1.7% |
| gpt-oss-20b-MXFP4.gguf (dense read, active-frac 1.0) | 144 x 80.2 | 0.271 | 0.267 | +1.5% |

disk-stream, one point before the headroom-cap policy (4ae6e13) banned small cgroup caps:
Qwen3.5-2B-Q4_K_M, prism-b10787 llama-bench `-t 4 -p 0 -n 16 -r 1 -lm mmap`, 1 GiB cap,
disk_read 0.181 GB/s: predicted 0.481, measured 0.416 tok/s (+15.6%). Not re-measured; it is
predicted only from now on.

Verdict: on this box layer streaming is PCIe-bound (3.3 GB/s) and is 3-10x slower than CPU decode
from RAM (19.5 GB/s read stream), so the planner only picks it when the weights do not fit in RAM.
It is the right mode for VRAM-only hosts, and for MoE with `--active-frac` (only active experts
streamed). The measurement covers transport, not G84 compute (no sm_11 matmul kernels yet).
