#!/bin/sh
# shellcheck shell=sh
# HERMES ESCALATION-READY CONFIGURATION
# Default effort level: ESCALATED (handles wishy-washy models with hand-holding)
#
# When to use this config:
# - Default graph mode usage when you want escalation proxy active
# - Models that might be borderline on context, quant, or capability
# - Situations where you want the system to hand off to heavier models
#
# When NOT to use:
# - Single-model mode (--mode single) — no router/proxy available
# - When you explicitly want direct node execution without hand-offs
#
# Installation: copy to ~/.hermes/config/hermes-config.sh or source directly

# EXPORT THESE DEFAULTS so every hermes.sh invocation is escalation-ready:
export HERMES_ESCALATE=1          # --escalate: always enable escalation proxy
export HERMES_ACCEPT_LICENSES=1   # --accept-licenses: auto-accept licenses
export HERMES_MIN_CTX_FLOOR=65536 # hermes-agent's 64K floor enforcement
export HERMES_LIGHT_MODEL=""      # empty = no light model by default (set NODE name if desired)
export HERMES_NO_SWAP_BACK=1      # --no-swap-back: keep model context between requests

# FUNCTION: run hermes with escalation-ready defaults
hermes_escalation_ready() {
    local flags="--mode graph"
    
    # Always add escalation if in graph mode
    if [ "${HERMES_ESCALATE:-0}" = "1" ]; then
        flags="$flags --escalate"
    fi
    
    # Always auto-accept licenses
    if [ "${HERMES_ACCEPT_LICENSES:-0}" = "1" ]; then
        flags="$flags --accept-licenses"
    fi
    
    # Add no-swap-back if enabled
    if [ "${HERMES_NO_SWAP_BACK:-0}" = "1" ]; then
        flags="$flags --no-swap-back"
    fi
    
    # Add light model if specified
    if [ -n "${HERMES_LIGHT_MODEL:-}" ]; then
        flags="$flags --light ${HERMES_LIGHT_MODEL}"
    fi
    
    # Pass through any additional args
    local extra_args=("$@")
    
    exec python3 scripts/hermes_modes.py $flags "${extra_args[@]}"
}

# Example usages (source this file then run):
#   hermes_escalation_ready --model coder
#   hermes_escalation_ready --model coder --client desktop --yes
#   hermes_escalation_ready --mode single --model coder
