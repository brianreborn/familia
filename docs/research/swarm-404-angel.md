# Security applications for 0.3.0: catalog, guardian apps, and fetch/render threats

Issue: https://github.com/brianreborn/familia/issues/404
Runner: angel (stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live)
Generated: 2026-11-11 06:07 PST
Approved-content-sha256: 52bfb168542851c248af0d34cc5504fa1b118c879639029316017c43320d406f

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18120); treat it as unverified until reviewed.

## 1. Read-only probe (measured on angel)

stamp v=1 host=angel role=swarm-pull prog=swarm-pull@0.2.6-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue Summary

The issue asks for a security review of the security-relevant menu/internal entries and the virtual app catalog in the Familia project. The goal is to identify potential security threats and ensure that all applications are safe to use.

## Proposed Approach

1. **Inventory the security-relevant menu/internal entries**: This involves reviewing the `scripts/menu-items.txt` and `scripts/menu-internal.txt` files to identify all security-relevant applications and their functionalities. For each entry, determine what it can start, whether it needs a license/operator confirm, and whether it can reach the network or print untrusted text.

2. **Threat review of the #397 fetch path**: This involves reviewing the design or current spike of the virtual app catalog to identify potential security threats. The focus will be on cache poisoning, untrusted issue title/body rendering, token scope, and fail-soft offline behavior.

3. **Check `ui_bridge.py` / menu rendering against L15**: This involves confirming whether control-character stripping is still missing in the `ui_bridge.py` file and file or fix against `main` if so.

4. **Confirm `guardian_ready.py` is still off-line and never auto-activates weights**: This involves checking whether the `guardian_ready.py` script is still off-line and never auto-activates weights.

5. **Post a same-day report**: This involves summarizing the inventory table, catalog threat notes, and any fix PR or follow-up filed against `main`.

## Risks and Test Ideas

- **Cache poisoning**: Ensure that the cache file is not writable by unauthorized users and that the TTL is set appropriately.
- **Untrusted issue title/body rendering**: Ensure

-- swarm/angel
