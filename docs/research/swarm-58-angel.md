# Survey (Sep?Oct 2026): Engines ? inference runtimes, quantization & kernels

Issue: https://github.com/brianreborn/familia/issues/58
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:16 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #58: Survey (Sep?Oct 2026): Engines for inference runtimes, quantization & kernels

### Part of the Sep?Oct 2026 survey of @BrianReborn_alt reposts and quote posts (window **[number] ? [number] PT**), following up #20.

#### Model names, sizes and claims come from the posts. HF/GitHub details were checked via the public HF/GitHub/arXiv APIs on [number] where a repo or paper could be identified. **"unresolved"** means the post gave no repo/paper link and none could be matched with confidence, so nothing there is guessed.

#### Fit key (familia target: ~15-year-old devices; miryam ~4.2 GiB model budget, qodesh CPU, 8600 GT GPU): **fits** = ?1 GB and CPU-friendly ? **maybe** = 1?5 GB or needs an unverified runtime ? **too big** = beyond that.

#### Runtimes and quantization tools that could sit next to (or replace) the pinned llama.cpp. Already tracked from #20: Uzu (#21 in code-bootstraps), DeepGEMM, FIT-GGUF, SAS, LittleBit.

### Items

- [ ] **[Magnitude (open-source inference engine)](https://github.com/magnitudedev/magnitude)** ? Tunes its kernels on the host machine. Post claims >2? Ollama on the same hardware, no new hardware required. Apache-2.0, 7.2k?.
  - Size: engine (host

-- swarm/angel
