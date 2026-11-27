"""The protocol probe verifies both legs without executing a host tool."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import probe_tool_roundtrip as probe  # noqa: E402


def test_result_leg_disables_further_calls_and_allows_completion(monkeypatch, tmp_path):
    key = tmp_path / "api-keys"
    key.write_text("test-only-key\n")
    seen = []

    def fake_completion(_url, _key, body, _timeout):
        seen.append(json.loads(json.dumps(body)))
        if len(seen) == 1:
            return {"choices": [{"finish_reason": "tool_calls", "message": {
                "tool_calls": [{"id": "call-1", "type": "function", "function": {
                    "name": "familia_probe", "arguments": "{}"}}]}}]}
        receipt = json.loads(body["messages"][-1]["content"])["receipt"]
        return {"choices": [{"finish_reason": "stop", "message": {"content": receipt}}]}

    monkeypatch.setattr(probe, "completion", fake_completion)
    code, report = probe.run("http://127.0.0.1:18080", "coder", key, 10)
    assert code == 0 and report["status"] == "pass"
    assert seen[0]["tool_choice"] == "required"
    assert seen[1]["tool_choice"] == "none" and seen[1]["max_tokens"] == 512
