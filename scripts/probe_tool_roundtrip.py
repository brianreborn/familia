#!/usr/bin/env python3
"""Check structured tool calling through a graph gateway without executing host tools.

This is a protocol gate, not a full harness acceptance test. The declared tool
returns a synthetic receipt; no command or file access is exposed to the model.
"""
from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import familia_auth


def endpoint(base_url: str) -> tuple[str, int]:
    parsed = urllib.parse.urlsplit(base_url)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment):
        raise ValueError("base URL must be an HTTP(S) endpoint without userinfo, query, or fragment")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    base = base_url.rstrip("/")
    return base + ("/chat/completions" if parsed.path.rstrip("/").endswith("/v1") else "/v1/chat/completions"), port


def completion(url: str, key: str, body: dict, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.load(response)
    if not isinstance(result, dict) or not result.get("choices"):
        raise ValueError("response has no choices")
    return result


def run(base_url: str, model: str, key_file: Path | None, timeout: int) -> tuple[int, dict]:
    url, port = endpoint(base_url)
    path = key_file or Path(familia_auth.instance_key_file(port=port))
    key = familia_auth._read(str(path.expanduser()))
    if not key:
        raise ValueError("caller key file is missing or empty")
    receipt = secrets.token_hex(8)
    body = {
        "model": model,
        "messages": [{"role": "user", "content": "Call familia_probe to obtain a receipt. After the tool responds, repeat its receipt exactly."}],
        "tools": [{"type": "function", "function": {
            "name": "familia_probe", "description": "Return a receipt for a protocol check",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        }}],
        "tool_choice": "required", "temperature": 0, "max_tokens": 128, "stream": False,
    }
    started = time.monotonic()
    first = completion(url, key, body, timeout)
    first_choice = first["choices"][0]
    message = first_choice.get("message") or {}
    calls = message.get("tool_calls") or []
    result = {"model": model, "tool_calls": len(calls),
              "first_finish_reason": first_choice.get("finish_reason"),
              "elapsed_ms": round((time.monotonic() - started) * 1000)}
    if not calls:
        return 2, dict(result, status="fail", phase="structured_call")
    call = calls[0]
    if call.get("type") != "function" or (call.get("function") or {}).get("name") != "familia_probe" or not call.get("id"):
        return 2, dict(result, status="fail", phase="tool_identity")
    body["messages"].extend([message, {"role": "tool", "tool_call_id": call["id"],
                                      "content": json.dumps({"receipt": receipt})}])
    body.pop("tool_choice")
    second = completion(url, key, body, timeout)
    answer = (second["choices"][0].get("message") or {}).get("content") or ""
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    result["receipt_echoed"] = receipt in answer
    if not result["receipt_echoed"]:
        return 2, dict(result, status="fail", phase="tool_result_continuation")
    return 0, dict(result, status="pass", phase="complete")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True, help="graph gateway origin or /v1 base URL")
    parser.add_argument("--model", required=True, help="routable alias advertised by /v1/models")
    parser.add_argument("--api-key-file", type=Path, help="caller key file; defaults to the local gateway port's instance file")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    try:
        status, report = run(args.base_url, args.model, args.api_key_file, args.timeout)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, urllib.error.URLError) as error:
        report = {"status": "error", "phase": "request", "error_type": type(error).__name__}
        if isinstance(error, urllib.error.HTTPError):
            report["http_status"] = error.code
        status = 3
    print(json.dumps(report, sort_keys=True))
    return status


if __name__ == "__main__":
    sys.exit(main())
