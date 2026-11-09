#!/usr/bin/env python3
"""Interactive Terminal Dashboard & UI Inspector for the running llama-server / protomodel."""

import json, os, sys, time, urllib.request

URL = os.environ.get("FAMILIA_UI_URL", "http://127.0.0.1:9941")

def get_json(path):
    try:
        with urllib.request.urlopen(f"{URL}{path}", timeout=2) as r:
            return json.load(r)
    except Exception as e:
        return {"error": str(e)}

def render_dashboard():
    props = get_json("/props")
    slots = get_json("/slots")
    models = get_json("/v1/models")

    if "error" in props:
        print(f"\033[1;31m[!] Cannot connect to llama-server on {URL}: {props['error']}\033[0m")
        return

    print("\033[2J\033[H", end="")
    print("\033[1;36m========================================================================\033[0m")
    print(f"\033[1;32m  FAMILIA PROTOMODEL / LLAMA-UI LIVE COCKPIT  \033[0m (\033[4m{URL}/\033[0m)")
    print("\033[1;36m========================================================================\033[0m")
    
    # Model details
    alias = props.get("model_alias", "unknown")
    ftype = props.get("model_ftype", "unknown")
    mpath = os.path.basename(props.get("model_path", ""))
    print(f"\033[1mModel Alias:\033[0m    {alias} ({ftype})")
    print(f"\033[1mWeights File:\033[0m   {mpath}")
    print(f"\033[1mWeb UI:\033[0m         {'Enabled (Svelte bundle active)' if props.get('ui') else 'Disabled'}")

    # Slot state
    print("\n\033[1;33m--- Active Engine Slots ---\033[0m")
    if isinstance(slots, list):
        for s in slots:
            sid = s.get("id", 0)
            ctx = s.get("n_ctx", 0)
            spec = s.get("speculative", False)
            proc = s.get("is_processing", False)
            task = s.get("id_task", "-")
            status_color = "\033[32mIDLE" if not proc else "\033[33mPROCESSING"
            print(f"  Slot #{sid} | Context: {ctx} tokens | Speculative: {spec} | Status: {status_color}\033[0m (Task {task})")
    else:
        print("  Slots data unavailable")

    # Exposed Models / Routes
    print("\n\033[1;33m--- Exposed Routes & Endpoints ---\033[0m")
    for m in (models.get("data") or []):
        mid = m.get("id", "")
        caps = ",".join(m.get("capabilities", [])) if "capabilities" in m else "chat"
        print(f"  • {mid:<15} [capabilities: {caps}]")

    print("\n\033[1;36m------------------------------------------------------------------------\033[0m")
    print("\033[2m  To view in browser, run: sh scripts/open_ui.sh or visit: " + URL + "/\033[0m")
    print("\033[1;36m========================================================================\033[0m")

if __name__ == "__main__":
    render_dashboard()
