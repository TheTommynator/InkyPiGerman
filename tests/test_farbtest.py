import base64
import struct
import sys
import zlib
from pathlib import Path

import pytest

# Die Plugins importieren relativ zu src/ (wie beim Start von InkyPi)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils.eink_farben import (  # noqa: E402
    MISCHUNGEN, NUR_FLAECHE, PALETTEN, PIGMENTE, PLATZHALTER, ROLLEN, css_farbe, css_flaeche, ist_farbe,
    muster_einsetzen, muster_png, palette, png, rollen_farben, schrift_auf, titel,
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


# --- Farbrollen und Platzhalter ---

def test_farbrollen_aus_dem_farbtest():
    assert all(ist_farbe(name) for name in ROLLEN.values())
    # Ergebnis des Farbtests auf dem Waveshare-Display
    assert ROLLEN["blau"] == "blau"
    assert ROLLEN["gelb"] == "gelb_orange_75"
    assert ROLLEN["orange"] == "rot_orange_50"
    assert {"blau", "gelb"} <= NUR_FLAECHE and "rot" not in NUR_FLAECHE
    assert [schrift_auf(r) for r in ("rot", "gruen", "blau", "gelb", "orange", "violett")] == [
        "weiss", "weiss", "weiss", "schwarz", "schwarz", "weiss"]


def test_platzhalter_sind_eindeutig():
    farben = PALETTEN["waveshare"]
    werte = list(PLATZHALTER.values())
    assert len(set(werte)) == len(MISCHUNGEN)
    assert not set(werte) & set(farben.values())
    assert css_farbe("rot", farben) == "#ff0000"
    assert css_farbe("gelb_orange_75", farben) == PLATZHALTER["gelb_orange_75"]
    rollen = rollen_farben(farben)
    assert rollen["blau"] == "#0000ff" and rollen["gelb"] == PLATZHALTER["gelb_orange_75"]


def test_muster_einsetzen():
    for modul in ("PIL", "numpy"):
        pytest.importorskip(modul)
    from PIL import Image

    farben = PALETTEN["waveshare"]
    bild = Image.new("RGB", (6, 4), "#ffffff")
    for x in range(1, 5):
        for y in range(4):
            bild.putpixel((x, y), tuple(int(PLATZHALTER["gelb_orange_75"][i:i + 2], 16) for i in (1, 3, 5)))
    bild.putpixel((5, 0), (0, 0, 0))
    ergebnis = muster_einsetzen(bild, farben)
    gelb, orange = (255, 255, 0), (255, 128, 0)
    # Muster nach absoluter Position: an (1,1) und (3,1) … Orange, sonst Gelb
    assert [ergebnis.getpixel((x, 1)) for x in range(1, 5)] == [orange, gelb, orange, gelb]
    assert [ergebnis.getpixel((x, 0)) for x in range(1, 5)] == [gelb] * 4
    # Alles andere bleibt unverändert
    assert ergebnis.getpixel((0, 0)) == (255, 255, 255) and ergebnis.getpixel((5, 0)) == (0, 0, 0)


# --- Plugin (braucht die Laufzeit-Abhängigkeiten) ---

class GeraetDummy:
    def __init__(self, **werte):
        self.werte = {"display_type": "epd7in3f", **werte}

    def get_resolution(self):
        return (800, 480)

    def get_config(self, schluessel, default=None):
        return self.werte.get(schluessel, default)


def plugin_mit_erfassung():
    for modul in ("requests", "PIL", "jinja2", "numpy"):
        pytest.importorskip(modul)
    from plugins.farbtest.farbtest import Farbtest

    plugin = Farbtest({"id": "farbtest"})
    erfasst = {}

    def render_image(dimensions, html, css, params):
        from PIL import Image
        erfasst.update(params, dimensions=dimensions)
        return Image.new("RGB", (2, 2), PLATZHALTER["rot_blau_50"])
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
    plugin.generate_image({}, GeraetDummy())
    assert params["tafel"] == "grundfarben" and params["palette_name"] == "Waveshare"
    assert [f["name"] for f in params["bunte"]] == ["rot", "gruen", "blau", "gelb", "orange"]

    plugin.generate_image({"tafel": "mischungen"}, GeraetDummy(display_type="inky", orientation="vertical"))
    assert params["tafel"] == "mischungen" and params["palette_name"] == "Inky"
    assert params["hochformat"] and params["dimensions"] == (480, 800)

    with pytest.raises(RuntimeError):
        plugin.generate_image({"tafel": "quatsch"}, GeraetDummy())


def test_rollentafel_setzt_muster_ein():
    plugin, params = plugin_mit_erfassung()
    bild = plugin.generate_image({"tafel": "rollen"}, GeraetDummy())
    assert params["tafel"] == "rollen" and len(params["rollen"]) == len(ROLLEN) - 1
    gelb = next(r for r in params["rollen"] if r["rolle"] == "Gelb")
    assert gelb["farbe"] == PLATZHALTER["gelb_orange_75"] and gelb["schrift"] == "#000000" and gelb["nur_flaeche"]
    # Violett-Platzhalter wurde zu Rot und Blau im Schachbrett
    assert sorted(farbe for _, farbe in bild.getcolors()) == [(0, 0, 255), (255, 0, 0)]


def test_kantenpixel_werden_zugeordnet():
    for modul in ("PIL", "numpy"):
        pytest.importorskip(modul)
    from PIL import Image

    farben = PALETTEN["waveshare"]
    p = tuple(int(PLATZHALTER["gelb_orange_75"][i:i + 2], 16) for i in (1, 3, 5))
    fast_platzhalter = tuple(round(0.8 * c) for c in p)          # 80 % Platzhalter, 20 % Schwarz
    fast_schwarz = tuple(round(0.2 * c) for c in p)              # 20 % Platzhalter, 80 % Schwarz
    halb_weiss = tuple(round(0.3 * c + 0.7 * 255) for c in p)    # Kante zu Weiß
    bild = Image.new("RGB", (4, 1))
    for x, farbe in enumerate((p, fast_platzhalter, fast_schwarz, halb_weiss)):
        bild.putpixel((x, 0), farbe)
    ergebnis = [muster_einsetzen(bild, farben).getpixel((x, 0)) for x in range(4)]
    assert ergebnis[0] in ((255, 255, 0), (255, 128, 0))
    assert ergebnis[1] in ((255, 255, 0), (255, 128, 0))
    assert ergebnis[2] == (0, 0, 0)
    assert ergebnis[3] == (255, 255, 255)


def test_benachbarte_mischungen_bleiben_getrennt():
    for modul in ("PIL", "numpy"):
        pytest.importorskip(modul)
    from PIL import Image

    farben = PALETTEN["waveshare"]
    bild = Image.new("RGB", (len(PLATZHALTER) * 2, 2))
    for i, platzhalter in enumerate(PLATZHALTER.values()):
        for x in (2 * i, 2 * i + 1):
            for y in (0, 1):
                bild.putpixel((x, y), tuple(int(platzhalter[j:j + 2], 16) for j in (1, 3, 5)))
    ergebnis = muster_einsetzen(bild, farben)
    for i, mischung in enumerate(MISCHUNGEN.values()):
        erwartet = {tuple(int(farben[p][j:j + 2], 16) for j in (1, 3, 5)) for p in (mischung.a, mischung.b)}
        gefunden = {ergebnis.getpixel((x, y)) for x in (2 * i, 2 * i + 1) for y in (0, 1)}
        assert gefunden == erwartet, mischung.name
