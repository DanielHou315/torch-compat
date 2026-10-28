"""Tests for filling curated-data gaps from vendor sources (no network)."""

import json
from pathlib import Path

import pytest

from sync_curated_data import (
    find_missing,
    first_redistrib,
    insert_entry,
    parse_gfx_targets,
    parse_gpu_arch_list,
)

DATA = Path(__file__).resolve().parent.parent / "data"


class TestFirstRedistrib:
    INDEX = (
        '<a href="redistrib_13.3.0.json">'
        '<a href="redistrib_13.4.2.json"><a href="redistrib_13.4.1.json">'
        '<a href="redistrib_13.40.0.json">'
    )

    def test_picks_earliest_patch(self):
        assert first_redistrib(self.INDEX, "13.4") == "redistrib_13.4.1.json"
        assert first_redistrib(self.INDEX, "13.3") == "redistrib_13.3.0.json"

    def test_missing(self):
        assert first_redistrib(self.INDEX, "13.5") is None


def test_parse_gpu_arch_list():
    out = "compute_75\ncompute_80\ncompute_90\ncompute_90a\ncompute_100f\ncompute_121\n"
    assert parse_gpu_arch_list(out) == ["7.5", "8.0", "9.0", "10.0", "12.1"]


def test_parse_gfx_targets_uses_curated_order():
    html = "<td>gfx1201</td><td>gfx90a</td><td>gfx1030, gfx908</td><td>gfx90a</td>"
    assert parse_gfx_targets(html) == ["gfx908", "gfx90a", "gfx1030", "gfx1201"]


class TestInsertEntry:
    def test_keeps_layout(self):
        text = (DATA / "rocm_support.json").read_text()
        new = insert_entry(text, "support", "99.0", ["gfx908", "gfx1201"])
        assert new.startswith(text[: text.rindex("]") + 1] + ",\n")
        assert '\n    "99.0": ["gfx908", "gfx1201"]\n  }\n}\n' in new
        assert json.loads(new)["support"]["99.0"] == ["gfx908", "gfx1201"]

    @pytest.mark.parametrize("section", ["linux", "windows"])
    def test_targets_named_section(self, section):
        text = (DATA / "cuda_drivers.json").read_text()
        new = json.loads(insert_entry(text, section, "99.0", None))
        other = {"linux": "windows", "windows": "linux"}[section]
        assert new[section]["99.0"] is None
        assert "99.0" not in new[other]


def test_find_missing():
    matrix = {"combos": [
        {"accel": "cuda", "accel_ver": "13.4"},
        {"accel": "cuda", "accel_ver": "13.3"},
        {"accel": "rocm", "accel_ver": "7.2.1"},
        {"accel": "rocm", "accel_ver": "10.0"},
    ]}
    drivers = {"linux": {"13.3": "610.43.02"}}
    sms = {"support": {"13.3": [], "13.4": []}}
    rocm = {"support": {"7.2": []}}
    assert find_missing(matrix, drivers, sms, rocm) == (["13.4"], [], ["10.0"])
