# 0.5.0 swarm worker: validate local model route before claims

Issue: https://github.com/brianreborn/familia/issues/792
Runner: galaxy2 (stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-27 08:30 PST
Approved-content-sha256: 34cd8196b9fd71f6999af2359049105a9c9622ed5af52c313e98539015e4e9ae

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:18080); treat it as unverified until reviewed.

## 1. Read-only probe (measured on galaxy2)

stamp v=1 host=galaxy2 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

# Issue #792 ? 0.5.0 swarm worker: validate local model route before claims  

## (a) What the issue asks  
The swarm worker can start with a *stale* local model URL or an alias that is not present in the graph catalog. It only fails after it actually **claims** work, leading to idle or failure later. We need to add an early, bounded check before any claim:

- Verify the configured **localhost endpoint** (address and port) is still valid.  
- If a model alias is supplied, confirm that the alias resolves via the graph catalog.  
- Use the **caller key file** for authentication when needed, but report precise errors without printing the key material.  

The check should be lightweight ? it must not invoke a model on every idle poll and must keep existing dry?run/approval boundaries intact.

---

## (b) Proposed approach & files/components  

### High?level design  
Create a new function `validate_local_model(cfg)` that returns one of:

- `"ok"` ? all checks pass.  
- `"stale_local_url: <port>"` ? local URL points to an unexpected port/address.  
- `"alias_missing_in_catalog"` ? alias is provided but not routable in the graph catalog.  
- `"rejected_key"` ? caller key file exists but fails verification (or no key file).  

The function performs only **local** operations: string parsing, existence checks on files, and a lightweight lookup in the existing graph?catalog resolver. It does not call the model or run any network request to it.

### Where it fits  
Insert the check at the top of `claim_work()` (or the idle?poll entry point) **before** claiming work. Existing dry?run/approval logic stays unchanged; just add this early validation.

### Likely files & modules  

| Component | Role |
|-----------|------|
| `worker/config.py` (or equivalent config loader) ? provides `model_url`, optional `alias`, and path to `caller_key_file`. |
| `graph_catalog/resolver.py` ? existing function that tells whether an alias is routable. |
| `key_loader/verify_key.py` ? utility that reads the caller key file and optionally verifies a signature without printing the content. |
| New module / extension in `swarm_worker/` (e.g., `local_model_checker.py`). |

### Sketch of new function  

```python
import os

def validate_local_model(cfg):
    """Return status string for local model readiness.

    Parameters:
        cfg: dict from worker config, must contain at least 'model_url'.
                Optional keys: 'alias', 'caller_key_file'.

    Returns:
        str ? one of "ok", or specific error messages.
    """
    # 1. Basic URL check
    url = cfg.get('model_url')
    if not url:
        return "missing model URL"
    if url.startswith('http://localhost'):
        port = int(url.split(':')[-1])
        allowed_ports = [8000, 8080]   # unknown ? needs confirmation
        if port not in allowed_ports:
            return f"stale local model port {port}"
    # 2. Alias resolution (if provided)
    alias = cfg.get('alias')
    if alias and alias != "default":
        if graph_catalog.resolve(alias):   # existing resolve returns bool
            pass
        else:
            return "model alias absent from graph catalog"
    # 3. Caller key verification (only if file exists)
    key_file = cfg.get('caller_key_file')
    if key_file and os.path.isfile(key_file):
        ok = caller_key_verify(cfg, key_file)   # returns bool
        if not ok:
            return "rejected caller key"
    else:
        return None   # no key needed or file missing is OK?
    return "ok"
```

*Notes*:  
- `graph_catalog.resolve(alias)` must exist and return a boolean indicating routability.  
- `caller_key_verify(cfg, key_file)` should read the file and optionally verify its signature without exposing the content in error messages.

### Documentation update  
- Edit `docs/swarm-worker-requirements.md` to add a bullet about ?early local model readiness check?.  
- Add a short section describing `validate_local_model`, its outcomes, and where it is invoked.

---

## (c) Risks & test ideas  

**Risks**  
- **Performance**: Extra string parsing and file?existence checks per idle poll could add latency. Keep them minimal; run only when idle or before claim.  
- **Key handling complexity**: How exactly does `caller_key_verify` work? Must avoid leaking key material in error messages.  
- **Port list uncertainty**: The set of allowed localhost ports is not yet known; a wrong assumption would cause false positives/negatives. Need confirmation from ops.  
- **Alias resolution dependency**: Relying on an existing catalog lookup may introduce version?sensitive behavior.

**Test ideas**  
1. Unit tests for `validate_local_model` covering each failure mode (missing URL, stale port, missing alias, bad key file).  
2. Integration test: start a worker with a deliberately stale URL and assert it returns `"stale local model port X"` before claiming work.  
3. Mock the graph?catalog resolver to return `False` for an alias; verify error message mentions absent alias.  
4. Provide a temporary caller?key file that fails signature check; ensure `validate_local_model` reports `"rejected caller key"`.  
5. Verify dry?run mode still passes the new check and does not alter approval boundaries.  
6. Benchmark idle polling latency with/without the check (unknown result ? placeholder).

---

## (d) Open questions  

- **Exact local endpoint format**: Is `model_url` always a full URL, or can it be just `localhost:port`? How is ?local? distinguished from external?  
- **Port list**: Which ports are considered valid for localhost in the swarm worker? Need to confirm with infrastructure.  
- **Caller key file location**: Should the path be absolute (e.g., `/etc/swarm/caller_key`) or relative to the worker process? How is it passed at startup?  
- **Alias routing semantics**: Does `graph_catalog.resolve(alias)` return a boolean, and what does ?routable? mean for an alias in this context? Any special handling needed?  
- **Boundedness of the check**: Should the validation run only when idle or before each claim? The issue says *do not* call a model on every idle poll ? clarify whether it should be tied to claim time.  
- **Dry?run impact**: In dry?run mode, does the early validation affect output? Preserve existing boundaries.

---  

*Prepared as a first?pass work note; unknown details (e.g., exact port list, key file path) are marked where needed.*

-- swarm/galaxy2
