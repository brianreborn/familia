#!/usr/bin/env python3
"""Box archetype enum + default shapes."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import box_archetypes as ba


def test_no_vm_in_enum():
    assert "vm" not in ba.HOST_KINDS
    ok, err = ba.validate_kind("vm")
    assert not ok and "obsolete" in err


def test_measurable_excludes_unknown():
    assert "unknown" not in ba.MEASURABLE_HOST_KINDS
    assert "desktop" in ba.MEASURABLE_HOST_KINDS


def test_shapes_complete_and_sensible():
    assert set(ba.DEFAULT_SHAPES) == ba.HOST_KINDS
    for kind, shape in ba.DEFAULT_SHAPES.items():
        assert "roles" in shape and "reserve_ram_mib" in shape
        assert "transports" in shape and "notes" in shape
        assert isinstance(shape["reserve_ram_mib"], int) and shape["reserve_ram_mib"] > 0
    assert ba.shape_for("phone")["roles"][0] == "decision"
    assert "coder" in ba.shape_for("desktop")["roles"]
    assert "coder" not in ba.shape_for("console")["roles"]
    assert ba.shape_for("1U")["reserve_ram_mib"] < ba.shape_for("3U")["reserve_ram_mib"]


def test_merge_shape_roles_orders_and_keeps_extras():
    ordered = ba.merge_shape_roles({"embed": 1, "coder": 1, "custom": 1}, "laptop")
    assert ordered[:3] == ["coder", "chat", "embed"]
    assert "custom" in ordered


def test_shape_header_mentions_kind():
    lines = ba.shape_header_lines("drone", "sky1")
    assert any("platform kind: drone" in l for l in lines)
    assert any("decision" in l for l in lines)
