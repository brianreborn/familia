import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import license_acceptance as la  # noqa: E402


def item(license_name, **kw):
    return {
        "kind": "model",
        "id": "example-model",
        "license": license_name,
        "category": "permissive",
        "source": "model card",
        "link": "https://example.invalid/card",
        **kw,
    }


def test_records_are_one_named_markdown_file_per_exact_license(tmp_path):
    directory = tmp_path / "accepted-licenses"
    first = item("Apache-2.0", evidence_sha256="a" * 64)
    second = item("MIT", evidence_sha256="b" * 64)

    first_path = la.record(first, "interactive", directory=directory)
    second_path = la.record(second, "interactive", directory=directory)

    assert first_path != second_path
    assert len(list(directory.glob("*.md"))) == 2
    assert la.is_accepted(first, directory)
    assert la.is_accepted(second, directory)
    saved = json.loads(open(first_path, encoding="utf-8").read().split("```json\n")[1].split("\n```")[0])
    assert saved["license"] == "Apache-2.0"
    assert saved["license_version"] == "Apache-2.0"
    assert saved["evidence_sha256"] == "a" * 64
    assert saved["accepted_by"] == "interactive"


def test_same_license_version_is_reused_but_changed_evidence_requires_consent(tmp_path):
    directory = tmp_path / "accepted-licenses"
    accepted = item("Apache-2.0", id="component-a", evidence_sha256="a" * 64)
    same_terms = item("Apache-2.0", id="component-b", evidence_sha256="a" * 64)
    changed_terms = item("Apache-2.0", id="component-a", evidence_sha256="c" * 64)

    la.record(accepted, "yes", directory=directory)

    assert la.is_accepted(same_terms, directory)
    assert not la.is_accepted(changed_terms, directory)


def test_explicit_record_replaces_invalid_existing_file(tmp_path):
    directory = tmp_path / "accepted-licenses"
    accepted = item("MIT", evidence_sha256="d" * 64)
    path = la.record(accepted, "interactive", directory=directory)
    with open(path, "w", encoding="utf-8") as stream:
        stream.write("invalid")

    assert not la.is_accepted(accepted, directory)
    la.record(accepted, "interactive", directory=directory)
    assert la.is_accepted(accepted, directory)


def test_identical_text_evidence_is_path_independent(tmp_path):
    first = tmp_path / "first" / "LICENSE"
    second = tmp_path / "second" / "LICENSE"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("same license terms", encoding="utf-8")
    second.write_text("same license terms", encoding="utf-8")

    assert la.evidence_sha256(str(first)) == la.evidence_sha256(str(second))


def test_unknown_consent_is_item_specific_and_explicit(tmp_path):
    directory = tmp_path / "accepted-licenses"
    unknown = item("unknown", category="unknown")
    other = item("unknown", id="other-model", category="unknown")

    assert la.record(unknown, "yes", directory=directory) is None
    la.record(unknown, "accept unknown", unknown_ok=True, directory=directory)

    assert la.is_accepted(unknown, directory)
    assert not la.is_accepted(other, directory)
