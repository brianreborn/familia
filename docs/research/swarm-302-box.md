# Investigate: Grok Bot app on Linux laptop stops repainting reliably over time (very low priority)

Issue: https://github.com/brianreborn/familia/issues/302
Runner: box (stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:54 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM3-1.7B-Uncensored-AD-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on box)

stamp v=1 host=box user=box uid=1000 session=/dev/pts/1 pid=947133 node=box-box role=swarm-pull runner=box prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

## 1. What the issue asks
Investigate: Grok Bot app on Linux laptop stops repainting reliably over time (very low priority)

## 2. Proposed approach
Try launching Grok Bot with `--disable-gpu`, test i915 PSR/FBC off, and reduce memory pressure (see #295). Correlate repaint events with systemd-oomd killing Firefox flatpak scope.

## 3. Files or components involved
- Grok Bot app (GNOME on Wayland)
- i915 kernel
- systemd-oomd (disabled but active)
- Firefox flatpak scope
- GNOME shell

## 4. Risks and test ideas
- Disabling `--disable-gpu` or switching to modesetting driver (i915 PSR/FBC off) may affect GPU usage.
- Reducing memory pressure (e.g., via swap or overcommit settings) may help, but could be risky.
- Correlating repaint events with systemd-oomd killing Firefox scope: check if repaint is a side effect of Firefox being killed, or if it's a separate hang.

## 5. Open questions
- What exactly is "repainting"? Is it a UI update triggered by a click? Or a re-render of the target after interaction?
- Is the hang caused by a window hang (target no longer exists) or by i915 display-freeze?
- How does the desktop behave after recovery? Was it fully functional?

Write: (a) what the issue asks, in your own words, (b) a proposed approach and the files or components likely involved, (c) risks and test ideas, (d)

-- swarm/box
