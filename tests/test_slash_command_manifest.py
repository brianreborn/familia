import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import slash_command_manifest as scm


FIXTURE = Path(__file__).resolve().parents[1] / "config" / \
    "slash-command-manifest.example.json"


def data():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_canonical_commands_resolve_for_consumers_without_aliases():
    manifest = scm.load_manifest(FIXTURE)
    result = scm.resolve(manifest, "minimal-client", "/familia-focus-begin")
    assert result.command == "familia-focus-begin"
    assert result.arguments == {}


def test_aliases_are_per_consumer_and_can_supply_fixed_arguments():
    manifest = scm.load_manifest(FIXTURE)
    result = scm.resolve(manifest, "gateway", "/coder")
    assert result.command == "familia-route"
    assert result.arguments == {"route": "coder"}
    with pytest.raises(scm.ManifestError, match="unknown slash command"):
        scm.resolve(manifest, "minimal-client", "/coder")
    renamed = scm.resolve(manifest, "renamed-client", "/start-focus")
    assert renamed.command == "familia-focus-begin"


def test_duplicate_aliases_for_one_consumer_are_rejected():
    manifest_data = data()
    manifest_data["consumers"]["gateway"]["aliases"].append(
        {"name": "begin", "command": "familia-focus-end"}
    )
    with pytest.raises(scm.ManifestError, match="duplicate alias 'begin'"):
        scm.parse_manifest(manifest_data)


def test_short_alias_cannot_override_a_canonical_name():
    manifest_data = data()
    manifest_data["consumers"]["gateway"]["aliases"].append(
        {"name": "familia-focus-begin", "command": "familia-focus-end"}
    )
    with pytest.raises(scm.ManifestError, match="reserved familia-|collides with a canonical"):
        scm.parse_manifest(manifest_data)


def test_help_and_unknown_token_list_only_exposed_names():
    manifest = scm.load_manifest(FIXTURE)
    assert scm.exposed_tokens(manifest, "gateway") == (
        "/begin", "/await", "/end", "/coder"
    )
    assert "/internal" not in scm.exposed_tokens(manifest, "gateway")
    assert scm.exposed_tokens(manifest, "minimal-client") == ()
    # Hidden canonical names remain resolvable but are not listed.
    assert scm.resolve(manifest, "gateway", "familia-internal-status").command == \
        "familia-internal-status"


def test_help_must_refer_to_a_registered_consumer_name():
    manifest_data = data()
    manifest_data["consumers"]["gateway"]["help"].append("missing")
    with pytest.raises(scm.ManifestError, match="not registered"):
        scm.parse_manifest(manifest_data)


def test_schema_version_and_resolution_inputs_are_strict():
    manifest_data = data()
    manifest_data["schema_version"] = True
    with pytest.raises(scm.ManifestError, match="schema_version must be 1"):
        scm.parse_manifest(manifest_data)
    manifest = scm.load_manifest(FIXTURE)
    with pytest.raises(scm.ManifestError, match="consumer name must be a string"):
        scm.resolve(manifest, [], "/begin")
    with pytest.raises(scm.ManifestError, match="slash command must be a string"):
        scm.resolve(manifest, "gateway", None)
