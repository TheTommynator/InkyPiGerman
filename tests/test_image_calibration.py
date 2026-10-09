import sys
from pathlib import Path

import pytest

# Die Plugins importieren relativ zu src/ (wie beim Start von InkyPi)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Ohne die Laufzeit-Abhängigkeiten (z. B. in der GitHub Action) überspringen
for module in ("PIL", "jinja2", "requests"):
    pytest.importorskip(module)

from plugins.image_calibration.image_calibration import (  # noqa: E402
    build_variants, format_value, grid_shape, parse_float, value_range,
)

BASE = {"saturation": 1.2, "contrast": 1.0, "sharpness": 1.0, "brightness": 1.0}


def test_parse_float_akzeptiert_komma_und_begrenzt():
    assert parse_float("1,5", 1.0) == 1.5
    assert parse_float("abc", 1.0) == 1.0
    assert parse_float("99", 1.0) == 5.0


def test_value_range_inklusive_enden():
    assert value_range(1.0, 2.0, 3) == [1.0, 1.5, 2.0]
    assert value_range(1.3, 2.0, 1) == [1.3]


def test_format_value():
    assert format_value(1.0) == "1.0"
    assert format_value(1.25) == "1.25"
    assert format_value(1.5) == "1.5"


def test_ein_parameter_uebernimmt_uebrige_werte():
    p1, p2, columns, variants = build_variants(
        {"primaryParameter": "contrast", "primaryFrom": "0.8", "primaryTo": "1.2", "primarySteps": "3"}, BASE)
    assert (p1, p2, columns) == ("contrast", None, None)
    assert [v["contrast"] for v in variants] == [0.8, 1.0, 1.2]
    assert all(v["saturation"] == 1.2 for v in variants)


def test_zwei_parameter_ergeben_raster():
    _, p2, columns, variants = build_variants({
        "primaryParameter": "saturation", "primarySteps": "4",
        "secondaryParameter": "sharpness", "secondarySteps": "2",
    }, BASE)
    assert p2 == "sharpness"
    assert columns == 4
    assert len(variants) == 8


def test_zu_viele_varianten():
    with pytest.raises(RuntimeError):
        build_variants({"primarySteps": "6", "secondaryParameter": "contrast", "secondarySteps": "3"}, BASE)


def test_gleicher_parameter_doppelt():
    with pytest.raises(RuntimeError):
        build_variants({"primaryParameter": "contrast", "secondaryParameter": "contrast"}, BASE)


def test_grid_shape():
    assert grid_shape(4, 800, 460) == (2, 2)
    assert grid_shape(6, 480, 780) == (2, 3)
    assert grid_shape(12, 800, 460, columns=4) == (4, 3)
