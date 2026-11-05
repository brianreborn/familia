
def _enforce_minimum_context(agent):
    # Reject windows below the 64K floor needed for reliable tool-calling; an explicit
    # positive model.context_length on LM Studio is allowed below the floor.
    _ctx = getattr(agent.context_compressor, "context_length", 0)
    # A local Ollama server serves num_ctx, not the GGUF's advertised window: a Modelfile or
    # model.ollama_num_ctx at 64K+ is a usable window even when the metadata says 40K (#100437).
    # Only a local endpoint can honour num_ctx, so a stale override never admits a hosted model.
    if agent._ollama_num_ctx and agent.base_url and is_local_endpoint(agent.base_url):
        _ctx = max(_ctx or 0, agent._ollama_num_ctx)
    _allow_lmstudio_explicit_below_floor = (
        str(agent.provider or "").strip().lower() == "lmstudio"
        and isinstance(agent._config_context_length, int)
        and not isinstance(agent._config_context_length, bool)
        and agent._config_context_length > 0
    )
    if _ctx and _ctx < MINIMUM_CONTEXT_LENGTH and not _allow_lmstudio_explicit_below_floor:
        floor_k = MINIMUM_CONTEXT_LENGTH // 1000
        if agent.base_url and is_local_endpoint(agent.base_url):
            # Any OpenAI-compatible local server (llama.cpp, vLLM, Ollama, ...) — the window is the
            # server's runtime setting, not the model's; never assume Ollama here (#87075).
            remedy = (
                f"Your local server is serving a {_ctx:,}-token window.  Start it with at least "
                f"{floor_k}K context (llama.cpp: -c {MINIMUM_CONTEXT_LENGTH}; vLLM: --max-model-len; "
                f"Ollama: OLLAMA_CONTEXT_LENGTH={MINIMUM_CONTEXT_LENGTH} or a Modelfile num_ctx), "
                f"or set model.ollama_num_ctx in config.yaml to the window it really serves "
                f"(at least {floor_k}K)."
            )
        else:
            remedy = (
                f"Choose a model with at least {floor_k}K context.  If your server "
                f"reports a window smaller than the model's true window, set "
                f"model.context_length in config.yaml to the real value "
                f"(this must be at least {floor_k}K)."
            )
        raise ValueError(
            f"Model {agent.model} has a context window of {_ctx:,} tokens, "
            f"which is below the minimum {MINIMUM_CONTEXT_LENGTH:,} required "
            f"by Hermes Agent.  {remedy}"
        )
