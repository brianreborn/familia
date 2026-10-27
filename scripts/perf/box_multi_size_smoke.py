#!/usr/bin/env python3
"""Box multi-size smoke: hit decision+coder, record pp/tg; default thinking off for Qwen-family.

Usage:
  python3 scripts/perf/box_multi_size_smoke.py [--out PATH] [--decision-port 18120] [--coder-port 18121]
Writes JSON array (same shape as install-notes/perf/2026-10-26-box-multi-size.json).
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path


def chat(port: int, prompt: str, *, thinking: bool | None, max_tokens: int = 32) -> dict:
    body: dict = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "seed": 0,
    }
    if thinking is not None:
        body["chat_template_kwargs"] = {"enable_thinking": thinking}
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        j = json.load(r)
    wall = time.perf_counter() - t0
    msg = (j.get("choices") or [{}])[0].get("message") or {}
    content = msg.get("content") or ""
    reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
    u = j.get("usage") or {}
    pt = float(u.get("prompt_tokens") or 0)
    ct = float(u.get("completion_tokens") or 0)
    return {
        "thinking": thinking,
        "wall_s": round(wall, 3),
        "content_len": len(content),
        "has_reasoning": bool(reasoning),
        "usage": u,
        "pp_t_s": (pt / wall) if wall > 0 and pt else None,
        "tg_t_s": (ct / wall) if wall > 0 and ct else None,
        "content_preview": content[:80],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--decision-port", type=int, default=18120)
    ap.add_argument("--coder-port", type=int, default=18121)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    rows = []
    rows.append({"node": "box-decision", "port": args.decision_port,
                 **chat(args.decision_port, "In one sentence, what is a decision?", thinking=None)})
    # Qwen-family: thinking false so content is non-empty
    rows.append({"node": "box-coder", "port": args.coder_port,
                 **chat(args.coder_port, "In one sentence, what is a box coder?", thinking=False)})
    rows.append({"node": "box-coder-think", "port": args.coder_port,
                 **chat(args.coder_port, "In one sentence, what is a box coder?", thinking=True, max_tokens=64)})
    # concurrent pair
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        f1 = ex.submit(chat, args.decision_port, "In one sentence, describe a recent decision.", None)
        f2 = ex.submit(chat, args.coder_port, "In one sentence, define compression.", False)
        rows.append({"node": "decision-co", "port": args.decision_port, **f1.result()})
        rows.append({"node": "coder-co", "port": args.coder_port, **f2.result()})
    text = json.dumps(rows, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
