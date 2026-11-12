# On-device speech nodes: Whistle STT and Paradee TTS

Issue: https://github.com/brianreborn/familia/issues/25
Runner: angel (stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 17:47 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel user=green uid=1001 session=/dev/pts/8 pid=32331 node=angel-green role=swarm-pull runner=angel prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue #25: On-device speech nodes: Whistle STT and Paradee TTS

### Source posts
- **Whistle, 16.9 MB on-device STT:** https://x.com/BrianReborn_alt/status/[number] and the canonical release RT https://x.com/BrianReborn_alt/status/[number]
- **Paradee, 8M-param / 9 MB Kokoro-distilled TTS:** https://x.com/BrianReborn_alt/status/[number]

**Unverified:** Sizes and claims come from the RT text. Repos, licenses, runtimes, and formats have not been checked yet.

### Tasks
- [ ] Add `stt` and `tts` node kinds (or audio roles) to the graph
- [ ] Catalog entries for Whistle and Paradee, placed first on phones and qodesh
- [ ] Launch test plus a short round-trip sample

### Proposed approach
1. **Add `stt` and `tts` node kinds to the graph:**
   - Define new node kinds in the graph schema to represent on-device speech recognition (STT) and text-to-speech (TTS) capabilities.
   - Update the graph schema to include these new node kinds.

2. **Catalog entries for Whistle and Paradee:**
   - Create catalog entries for Whistle and Paradee, placing them first on the phones and qodesh.
   - Ensure that the catalog entries are accurate and up-to-date.

3. **Launch test plus a short round-trip sample:**
   - Conduct a test to verify the functionality of Whistle and Paradee on the device.
   - Perform a

-- swarm/angel
