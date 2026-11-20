#!/usr/bin/env python3
"""Minimal stdio MCP server (stdlib only) for familia tests: tools echo + add. No network, no files."""
import json, sys

TOOLS = [
    {"name": "echo", "description": "Echo text back.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "add", "description": "Add two integers.",
     "inputSchema": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                     "required": ["a", "b"]}},
]

def handle(m):
    meth, p = m.get("method"), m.get("params") or {}
    if meth == "initialize":
        return {"protocolVersion": p.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
                "serverInfo": {"name": "familia-mcp-stub", "version": "0.1"}}
    if meth == "ping":
        return {}
    if meth == "tools/list":
        return {"tools": TOOLS}
    if meth == "tools/call":
        a = p.get("arguments") or {}
        if p.get("name") == "echo":
            text = "stub-echo:" + str(a.get("text", ""))
        elif p.get("name") == "add":
            text = str(int(a["a"]) + int(a["b"]))
        else:
            return {"content": [{"type": "text", "text": "unknown tool"}], "isError": True}
        return {"content": [{"type": "text", "text": text}], "isError": False}
    if meth in ("resources/list", "prompts/list"):
        return {meth.split("/")[0]: []}
    raise KeyError(meth)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    m = json.loads(line)
    if "id" not in m:  # notification
        continue
    try:
        out = {"jsonrpc": "2.0", "id": m["id"], "result": handle(m)}
    except KeyError as e:
        out = {"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32601, "message": f"method not found: {e}"}}
    sys.stdout.write(json.dumps(out) + "\n"); sys.stdout.flush()
