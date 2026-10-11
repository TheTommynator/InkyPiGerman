import base64
import struct
import sys
import zlib
from pathlib import Path

import pytest

# Die Plugins importieren relativ zu src/ (wie beim Start von InkyPi)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils.eink_farben import (  # noqa: E402
    MISCHUNGEN, PALETTEN, PIGMENTE, css_flaeche, ist_farbe, muster_png, palette, png, titel,
)


def png_pixel(daten):
    """Liest ein unkomprimiertes 8-Bit-RGB-PNG (wie von png() erzeugt) zurück."""
    assert daten[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, breite, hoehe = 8, b"", 0, 0
    while pos < len(daten):
        laenge, typ = struct.unpack(">I4s", daten[pos:pos + 8])
        inhalt = daten[pos + 8:pos + 8 + laenge]
        crc = struct.unpack(">I", daten[pos + 8 + laenge:pos + 12 + laenge])[0]
        assert crc == zlib.crc32(typ + inhalt) & 0xFFFFFFFF
        if typ == b"IHDR":
            breite, hoehe = struct.unpack(">II", inhalt[:8])
        elif typ == b"IDAT":
            idat += inhalt
        pos += 12 + laenge
    roh = zlib.decompress(idat)
    zeile = 1 + 3 * breite
    return [[tuple(roh[y * zeile + 1 + 3 * x:y * zeile + 4 + 3 * x]) for x in range(breite)] for y in range(hoehe)]


def test_palette_je_display():
    assert palette("epd7in3f") is PALETTEN["waveshare"]
    assert palette("inky_impression") is PALETTEN["inky"]
    assert palette(None)["blau"] == "#0000ff"
    for farben in PALETTEN.values():
        assert set(farben) == set(PIGMENTE)


def test_mischungen_bestehen_aus_zwei_pigmenten():
    for name, m in MISCHUNGEN.items():
        assert m.a in PIGMENTE and m.b in PIGMENTE and m.a != m.b
        assert name == f"{m.a}_{m.b}_{int(m.anteil * 100)}"
        pixel = sum(m.pixel(), [])
        assert pixel.count(m.a) == round(m.anteil * 4)
    assert titel("blau_weiss_75") == "Blau ¾ + Weiß"
    assert titel("gruen") == "Grün"
    assert ist_farbe("blau_weiss_50") and ist_farbe("rot") and not ist_farbe("lila")


def test_png_ist_pixelgenau():
    farben = PALETTEN["waveshare"]
    pixel = png_pixel(muster_png(MISCHUNGEN["blau_weiss_50"], farben))
    assert pixel == [[(0, 0, 255), (255, 255, 255)], [(255, 255, 255), (0, 0, 255)]]
    pixel = png_pixel(muster_png(MISCHUNGEN["gelb_orange_75"], farben))
    assert sum(pixel, []).count((255, 255, 0)) == 3
    assert png_pixel(png([[(1, 2, 3)]])) == [[(1, 2, 3)]]


def test_css_flaeche():
    farben = PALETTEN["waveshare"]
    assert css_flaeche("rot", farben) == "#ff0000"
    wert = css_flaeche("rot_weiss_50", farben)
    assert wert.startswith('url("data:image/png;base64,') and wert.endswith("0 0 / 2px 2px repeat")
    daten = base64.b64decode(wert.split(",", 1)[1].split('"')[0])
    assert png_pixel(daten)[0] == [(255, 0, 0), (255, 255, 255)]


def test_kalender_nutzt_dieselben_pigmente():
    from plugins.icloud_kalender.kalender_daten import EINK_PALETTEN
    assert EINK_PALETTEN["waveshare"] == ["#000000", "#00ff00", "#0000ff", "#ff0000", "#ffff00", "#ff8000"]
    assert EINK_PALETTEN["inky"][2] == PALETTEN["inky"]["blau"]


# --- Plugin (braucht die Laufzeit-Abhängigkeiten) ---

class GeraetDummy:
    def __init__(self, **werte):
        self.werte = {"display_type": "epd7in3f", **werte}

    def get_resolution(self):
        return (800, 480)

    def get_config(self, schluessel, default=None):
        return self.werte.get(schluessel, default)


def plugin_mit_erfassung():
    for modul in ("requests", "PIL", "jinja2"):
        pytest.importorskip(modul)
    from plugins.farbtest.farbtest import Farbtest

    plugin = Farbtest({"id": "farbtest"})
    erfasst = {}

    def render_image(dimensions, html, css, params):
        erfasst.update(params, dimensions=dimensions)
        return "bild"
    plugin.render_image = render_image
    return plugin, erfasst


def test_mischungstafel_ist_vollstaendig_und_nummeriert():
    for modul in ("requests", "PIL", "jinja2"):
        pytest.importorskip(modul)
    from plugins.farbtest.farbtest import MISCHUNGS_REIHEN, mischungs_kacheln
    kacheln = mischungs_kacheln(PALETTEN["waveshare"])
    assert [k["nummer"] for k in kacheln] == list(range(1, 25))
    assert all(len(reihe) == 6 for reihe in MISCHUNGS_REIHEN)
    # Jede Mischung des Katalogs kommt genau einmal vor
    assert sorted(k["name"] for k in kacheln if not k["rein"]) == sorted(MISCHUNGEN)
    assert kacheln[0]["titel"] == "Blau (rein)" and kacheln[0]["flaeche"] == "#0000ff"


def test_plugin_tafeln():
    plugin, params = plugin_mit_erfassung()
    assert plugin.generate_image({}, GeraetDummy()) == "bild"
    assert params["tafel"] == "grundfarben" and params["palette_name"] == "Waveshare"
    assert [f["name"] for f in params["bunte"]] == ["rot", "gruen", "blau", "gelb", "orange"]

    plugin.generate_image({"tafel": "mischungen"}, GeraetDummy(display_type="inky", orientation="vertical"))
    assert params["tafel"] == "mischungen" and params["palette_name"] == "Inky"
    assert params["hochformat"] and params["dimensions"] == (480, 800)

    with pytest.raises(RuntimeError):
        plugin.generate_image({"tafel": "quatsch"}, GeraetDummy())
