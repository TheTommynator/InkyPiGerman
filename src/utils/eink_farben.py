"""Farben für 7-Farben-E-Ink-Displays – zentral für alle Plugins.

Ein 7-Farben-Display kennt nur seine sieben Pigmente. Jede andere Farbe wird
vom Treiber in ein zufälliges Punktraster zerlegt. Dieses Modul bietet zwei
Dinge, die das vermeiden:

  - die reinen Pigmentfarben je Display (``palette``)
  - „Mischungen“: zwei Pigmente in einem festen, regelmäßigen 2×2-Pixelmuster.
    Aus etwas Abstand verschwimmt so ein Muster zu einer neuen Farbe (z. B.
    Blau + Weiß = helleres Blau), ohne das unruhige Rauschen des Treibers.

In CSS liefert ``css_flaeche(name, palette)`` den passenden Wert für
``background``. Das Muster ist eine winzige PNG-Kachel, die der Browser 1:1
kachelt – pixelgenau, solange die Seite ohne Zoom gerendert wird (wie beim
Screenshot der Plugins).

Welche Mischungen auf dem eigenen Display am besten wirken, zeigt das Plugin
„Farbtest“. Bewusst ohne Fremdbibliotheken, damit es sich in der GitHub Action
testen lässt.
"""

import base64
import struct
import zlib
from dataclasses import dataclass

PIGMENTE = ("schwarz", "weiss", "rot", "gruen", "blau", "gelb", "orange")

PIGMENT_NAMEN = {
    "schwarz": "Schwarz", "weiss": "Weiß", "rot": "Rot", "gruen": "Grün",
    "blau": "Blau", "gelb": "Gelb", "orange": "Orange",
}

# RGB-Werte, mit denen der jeweilige Treiber seine Pigmente anspricht
PALETTEN = {
    "waveshare": {
        "schwarz": "#000000", "weiss": "#ffffff", "rot": "#ff0000", "gruen": "#00ff00",
        "blau": "#0000ff", "gelb": "#ffff00", "orange": "#ff8000",
    },
    "inky": {
        "schwarz": "#1c181c", "weiss": "#ffffff", "rot": "#cd2425", "gruen": "#1dad23",
        "blau": "#1e1dae", "gelb": "#e7de23", "orange": "#d87b24",
    },
}


def palette(display_type=""):
    """Pigmentfarben für den konfigurierten Displaytyp (Name → „#rrggbb“)."""
    return PALETTEN["inky" if str(display_type or "").startswith("inky") else "waveshare"]


# Anteil der ersten Farbe → 2×2-Muster (True = erste Farbe)
MUSTER = {
    0.25: ((True, False), (False, False)),
    0.5: ((True, False), (False, True)),
    0.75: ((True, True), (True, False)),
}

ANTEIL_TEXT = {0.25: "¼", 0.5: "½", 0.75: "¾"}


@dataclass(frozen=True)
class Mischung:
    name: str
    a: str
    b: str
    anteil: float  # Anteil von Farbe a

    @property
    def titel(self):
        return f"{PIGMENT_NAMEN[self.a]} {ANTEIL_TEXT[self.anteil]} + {PIGMENT_NAMEN[self.b]}"

    def pixel(self):
        """Das 2×2-Muster als Pigmentnamen."""
        return [[self.a if p else self.b for p in reihe] for reihe in MUSTER[self.anteil]]


def _mischung(a, b, anteil):
    return Mischung(f"{a}_{b}_{int(anteil * 100)}", a, b, anteil)


# Katalog der getesteten Mischungen. Die Namen sind stabil, Plugins können sie
# direkt verwenden (z. B. css_flaeche("blau_weiss_50", palette)).
MISCHUNGEN = {m.name: m for m in (
    _mischung("blau", "weiss", 0.75),
    _mischung("blau", "weiss", 0.5),
    _mischung("blau", "weiss", 0.25),
    _mischung("blau", "gruen", 0.5),
    _mischung("blau", "gruen", 0.75),
    _mischung("gelb", "orange", 0.75),
    _mischung("gelb", "orange", 0.5),
    _mischung("gelb", "gruen", 0.75),
    _mischung("gelb", "weiss", 0.75),
    _mischung("orange", "weiss", 0.5),
    _mischung("rot", "orange", 0.5),
    _mischung("rot", "weiss", 0.5),
    _mischung("rot", "blau", 0.5),
    _mischung("gruen", "gelb", 0.5),
    _mischung("gruen", "weiss", 0.5),
    _mischung("gruen", "blau", 0.75),
    _mischung("schwarz", "weiss", 0.5),
    _mischung("schwarz", "weiss", 0.25),
)}


def ist_farbe(name):
    return name in PIGMENTE or name in MISCHUNGEN


def titel(name):
    if name in PIGMENTE:
        return PIGMENT_NAMEN[name]
    return MISCHUNGEN[name].titel


def _rgb(hex_farbe):
    h = hex_farbe.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def png(pixel_reihen):
    """Minimales RGB-PNG aus Zeilen von (r, g, b)-Tupeln – ohne Pillow."""
    hoehe, breite = len(pixel_reihen), len(pixel_reihen[0])
    roh = b"".join(b"\x00" + b"".join(bytes(p) for p in reihe) for reihe in pixel_reihen)

    def block(typ, daten):
        inhalt = typ + daten
        return struct.pack(">I", len(daten)) + inhalt + struct.pack(">I", zlib.crc32(inhalt) & 0xFFFFFFFF)

    kopf = struct.pack(">IIBBBBB", breite, hoehe, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + block(b"IHDR", kopf)
            + block(b"IDAT", zlib.compress(roh)) + block(b"IEND", b""))


def muster_png(mischung, farben):
    return png([[_rgb(farben[p]) for p in reihe] for reihe in mischung.pixel()])


def css_flaeche(name, farben):
    """CSS-Wert für ``background``: Pigment als Farbe, Mischung als Musterkachel."""
    if name in PIGMENTE:
        return farben[name]
    mischung = MISCHUNGEN[name]
    daten = base64.b64encode(muster_png(mischung, farben)).decode("ascii")
    return f'url("data:image/png;base64,{daten}") 0 0 / 2px 2px repeat'
