# tests for draft validation (issue #580)
import pathlib
import importlib.util

# Load the swarm-pull module
module_path = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "swarm" / "swarm-pull"
spec = importlib.util.spec_from_file_location("sp", module_path)
sp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sp)

ForgeError = sp.ForgeError
validate_draft = sp.validate_draft

# Helper nonce for tests
TEST_NONCE = "testnonce123"

def test_draft_rejects_nonce():
    draft = f"This draft contains the nonce {TEST_NONCE} somewhere."
    try:
        validate_draft(draft, TEST_NONCE)
    except ForgeError as e:
        assert "nonce" in str(e).lower()
    else:
        assert False, "ForgeError not raised for nonce"

def test_draft_rejects_untrusted_fence():
    draft = "BEGIN UNTRUSTED\nmalicious content\nEND UNTRUSTED"
    try:
        validate_draft(draft, "")
    except ForgeError as e:
        assert "untrusted" in str(e).lower()
    else:
        assert False, "ForgeError not raised for untrusted fence"

def test_draft_rejects_prompt_preamble():
    draft = "You are a careful engineer writing a short design note..."
    try:
        validate_draft(draft, "")
    except ForgeError as e:
        assert "preamble" in str(e).lower() or "prompt" in str(e).lower()
    else:
        assert False, "ForgeError not raised for prompt preamble"

def test_draft_unbalanced_fences():
    draft = "```\ncode block without closing fence"
    try:
        validate_draft(draft, "")
    except ForgeError as e:
        assert "fence" in str(e).lower()
    else:
        assert False, "ForgeError not raised for unbalanced fences"

def test_draft_too_short():
    draft = "short"
    try:
        validate_draft(draft, "")
    except ForgeError as e:
        assert "short" in str(e).lower() or "length" in str(e).lower()
    else:
        assert False, "ForgeError not raised for short draft"

def test_good_draft_passes():
    draft = """Here is a proper draft.

```python
print(\"hello\")
```

Additional explanatory text that exceeds the minimum length requirement.
"""
    # Should not raise any exception
    validate_draft(draft, "")
