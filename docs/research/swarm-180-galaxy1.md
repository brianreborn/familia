# High priority: bundled skills (on-demand + single-file AppImage-style bundle), starting with leanrea (REA replacement)

Issue: https://github.com/brianreborn/familia/issues/180
Runner: galaxy1 (stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct)
Generated: 2026-11-10 18:36 PST

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (llama-cli LFM2.5-1.2B-Instruct-Q4_K_M.gguf); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 user=u0_a439 uid=10439 session=1.6.2 pid=27384 node=galaxy1-u0_a439 role=swarm-pull runner=galaxy1 prog=swarm-pull@0.2-live mode=live forge_via=direct

No specialized probe for this issue.

## 2. Local model draft (unverified)

We'll do this in a single pass.

You are a careful engineer working on the familia project. I'm writing a short first-pass work note for this issue.

I need to create a bundled skill set for leanrea (REA) using the leanrea skill index.

**What does the issue ask?**
The issue wants to bundle leanrea (REA) into a single executable package, either as a standalone binary or a bundled skill, and make it available for on-demand use or as a permanent install. The goal is to provide a lightweight, offline-capable, and easy-to-use REA tool that can be installed and run without external dependencies.

**Proposed approach:**
1. Create a `skills/leanrea` folder with the REA CLI.
2. Use `familia` to generate a `graph.yaml` and `catalog.json` file.
3. Pin the REA to a specific commit hash, verify its license, and include it in a bundled package.
4. Package it as a standalone binary or a bundled skill with a `--prefix` and `--scope`.
5. Test both on-demand and permanent installation scenarios.

**Risks and test ideas:**
- **License compliance:** Ensure the REA is open source and properly licensed.
- **Offline availability:** Verify the bundle works without internet access.
- **Security:** Confirm the bundle is not malicious or has hidden permissions.
- **Compatibility:** Test across OSes (Linux, Windows, macOS, Termux) and ensure it works offline.

**Open questions:**
- How will the license check be implemented?
- What happens if the REA is modified or removed?
- Can the bundle be extended to other REAs?
- How will the bundle be distributed and used by the community?

Let me know if you'd like me to draft the actual README or sample `catalog.json` structure.

-- swarm/galaxy1
