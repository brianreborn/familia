# Add llama.cpp PGO support explicitly through familia menu commands.

Issue: https://github.com/brianreborn/familia/issues/676
Runner: surface1 (stamp v=1 host=surface1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live)
Generated: 2026-11-22 23:08 PST
Approved-content-sha256: 889a47c342cc27c86dcab3a2f5494351fd727240b4ed87ae72432f01b2ed79f0

Status: rough first pass by the swarm pull worker. Section 1 is a read-only
probe run on the runner host (measured). Section 2 is a draft from a small
local open model (http http://127.0.0.1:9931); treat it as unverified until reviewed.

## 1. Read-only probe (measured on surface1)

stamp v=1 host=surface1 role=swarm-pull prog=swarm-pull@0.2.9.3-live mode=live

No specialized probe for this issue.

## 2. Local model draft (unverified)

## Issue Summary

**Issue #676**: Add explicit "PGO" (Profile-Guided Optimization) support for `llama.cpp` engines through the `familia` project's top-level menu commands. The goal is to allow users to easily enable/disable PGO profiling on engines like `llama.cpp`, using their own operational data rather than relying solely on benchmarks.

This builds on prior discussions (#674, #675) about PGO and profiling but wants a **new top-level menu command** (e.g., "Optimization") in the `familia` UI to control profile-guided recompilation of engines with real user data.

---

## (a) What the issue asks

The user wants a way, via the `familia` project's main menu, to **turn on and off PGO profiling for llama.cpp-style engines** so that they can compile/optimize them using their own operational workloads. They want this to be a straightforward, top-level option:

- An explicit command (e.g., "Optimization") in the menu.
- Control over enabling/disabling PGO.
- Ability to recompile engines with profile guidance after profiling.
- Use of **real data / operational data** rather than synthetic benchmarks.

---

## (b) Proposed approach & likely files/components

### High-level plan
1. **Introduce a new top?level menu entry** under the optimization/engine configuration section in `familia`.
2. **Expose a flag** to the build system that tells the engine builder whether to generate PGO profiles from user data and then recompile with those profiles.
3. **Hook into llama.cpp?s PGO flags** (e.g., `-C profile=on/off` or similar) when building engines.

### Likely files / components

| Area | Component | Notes |
|------|-----------|-------|
| UI / Menu | `familia/src/menu/` or equivalent top?level menu definitions | Add a new command like ?Optimization? ? sub?commands: Profile, Recompile with profile. |
| Build system | `familia/CMakeLists.txt` (or per-engine CMake) | Pass a flag to the engine build step; possibly a new variable e.g., `PGO_ENABLED`. |
| Engine integration | `llama.cpp` wrapper / build scripts in `familia/engines/` or similar | Detect if an engine is built with PGO enabled/disabled. For llama.cpp, invoke its own profile?generation and recompilation steps when the flag changes. |
| Data handling | New input file or config for operational data (e.g., `.profile_data.json`) | Used to train profiles; not invented ? unknown where currently stored. |
| Profiling tooling | Existing profiling utilities in `familia` (if any) | Reuse if available, otherwise add a thin wrapper around llama.cpp?s profiler. |

### Sketch of changes

- **Menu command** (`Optimization`) ? opens sub?panel with options:
  - *Enable PGO* ? triggers profile collection from operational data and recompile.
  - *Disable PGO* ? stops profiling, disables any generated profiles.
  - *Recompile with profile guidance* ? rebuilds the engine using previously collected profiles.

- **Build flag** passed to `llama.cpp` build: e.g.,  
  ```
  CMAKE_ARGS="-DCMAKE_C_FLAGS='-O3 -march=native' ... -DLLAMA_CPP_ENABLE_PGO=ON"
  ```

---

## (c) Risks & test ideas

### Risks
1. **Compatibility with existing engine builds** ? Some engines may not expose PGO flags; need to guard or fallback.
2. **Data format for operational data** ? Unknown how to ingest real user logs/metrics into profiles. Need a schema.
3. **Recompilation time & disk space** ? Profiling and recompiling with new profiles could be slow on large datasets.
4. **Side effects of PGO** ? May change binary behavior; need regression tests for correctness after optimization.
5. **UI confusion** ? New top?level menu entry might clash with existing ?Optimization? or ?Build? sections.

### Test ideas (unknown specifics)
- Build a minimal `llama.cpp` engine wrapper and verify that passing `-DLLAMA_CPP_ENABLE_PGO=ON/OFF` changes build output.
- Create a small synthetic dataset of llama prompts + operational logs, run the profiler, inspect profile files.
- Run end?to?end: enable PGO via menu ? collect profiles ? recompile ? run inference and compare outputs to baseline (unknown if any difference).
- Regression tests for existing engines not affected by PGO.

---

## (d) Open questions

1. **How does `llama.cpp` expose PGO?**  
   - Is there an existing flag like `-C profile=on`? Or do we need to add it?
2. **Where is the operational data stored / how should it be supplied?**  
   - Will users provide a JSON/YAML file, or feed logs into llama.cpp?s profiler directly?
3. **Exact menu path & naming** ? Should it be ?Optimization?, ?Engine Optimization?, etc.? Need confirmation from product team.
4. **Integration with `familia` build system** ? Which CMake variables control PGO for engines? Are there per?engine overrides?
5. **Performance impact of recompiling with profiles** ? Unknown; need benchmarking on representative workloads.

---

## (e) Next steps

- Draft the new menu command in `menu/commands/*.md` or equivalent.
- Add a flag to engine build scripts and propagate to llama.cpp.
- Define a minimal data format for operational profiling (unknown).
- Implement tests using existing profiler utilities; run on a small llama.cpp example.

---

*All details above are based solely on the issue text. File paths, variable names, and exact behavior are unknown and need verification.*

-- swarm/surface1
