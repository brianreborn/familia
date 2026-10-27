"""Auto-loaded when this directory is on PYTHONPATH (familia hermes launch, #96).

Wraps hermes-agent ``tools.env_probe._build_probe_line`` so the "Python toolchain:"
system-prompt line is stable across process launches on the same host.
"""
try:
    import familia_env_probe_cache as _fepc
    _fepc.install_import_hook()
except Exception:
    # Never break hermes startup over an overlay failure.
    pass
