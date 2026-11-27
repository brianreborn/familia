# 0.5.0 monitor: remove obsolete default host and port entries

Issue: https://github.com/brianreborn/familia/issues/796
Runner: galaxy1 (stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-27 14:48 PST
Approved-content-sha256: d3520fc2579dc3da5160e71548f414467e8d2452e51258c9a47cc962401c554e

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18080); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy1)

stamp v=1 host=galaxy1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Work Note for Issue #796  

## (a) What the issue asks  

- The **Familia** project keeps a *default monitor inventory* that lists host identities and their ports.  
- In version?0.5.0 (and related sprint?#683) some entries are now obsolete: they refer to retired hosts or an old ?Angel? port.  
- Goal: **remove those obsolete entries** so the default?monitor invocation only reports the six active identities:  

  ```
  angel
  galaxy1
  galaxy2
  miryam
  note9
  surface1
  ```

- Keep address selection in local overlays or SSH aliases; do not commit private LAN addresses.  
- Preserve existing checks that detect model?process death and route availability.

## (b) Proposed approach & likely files/components  

1. **Locate the current default monitor inventory** ? it is probably defined in a configuration file such as `familia/default_monitor.yml` or `config/monitor_default.yaml`. A generation script (e.g., `scripts/generate_monitor.py`) may also write this data.  
2. **Identify and delete obsolete rows**: any host entry that is not one of the six listed above, especially old ?angel? entries with retired ports, should be removed or updated to point at the current service port.  
3. **Update address resolution**: leave IP/port look?ups in local environment variables or SSH alias files (e.g., `~/.ssh/aliases`, `.bashrc`). Do not hard?code private LAN addresses into the monitor file.  
4. **Keep existing checks** for model process death and route availability untouched ? they should continue to run as part of the monitor logic.  

*Likely files/components involved* (unknown exact names):  
- `default_monitor.yml` / `monitor_default.yaml` ? inventory definition.  
- Generation/update script that produces the above file.  
- SSH alias or local overlay configuration for address resolution.  
- Monitoring modules such as `process_monitor.py`, `route_checker.py` (or similar) that handle process?death and route?availability detection.

## (c) Risks & test ideas  

**Risks**  
- Other parts of the codebase may still import or reference removed host entries, causing runtime errors.  
- Removing an obsolete Angel port could affect services that rely on it; verify current service ports.  
- Graph?derived endpoint refactoring mentioned in #791 might be impacted ? leave that for a later PR.

**Test ideas (unknown specifics)**  
- Run the default monitor command after changes and confirm its output lists **only** the six intended identities.  
- Ensure ?angel? no longer appears as an active failure or obsolete port.  
- Simulate model?process death scenarios and verify existing checks still trigger.  
- Perform basic route?availability probes for each of the six hosts to confirm they remain reachable.

## (d) Open questions  

- Exact filename(s) that hold the default monitor inventory in this version?  
- Which ports are currently associated with ?angel? and which are considered obsolete?  
- How local overlays or SSH aliases are defined/used for address resolution; is there a central config for them?  
- Are there any other retired host entries besides the six to be removed?  

*All details above are unknown until inspected in the repository.*

-- swarm/galaxy1
