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

Für alles, was kein CSS-Hintergrund ist (SVG-Füllungen, Rahmen, Linien),
gibt es Platzhalter: ``css_farbe(name, palette)`` liefert für eine Mischung
eine eindeutige Ersatzfarbe, und ``muster_einsetzen(bild, palette)`` tauscht
deren Pixel im fertigen Screenshot gegen das Muster aus.

**Farbrollen** (``ROLLEN``) legen fest, welche Variante ein Plugin für „Gelb“,
„Orange“, „Grau“ usw. verwenden soll. Sie stammen aus dem Farbtest auf dem
Waveshare-Display des Nutzers (Fotos vom 11.10.2026):

  - Blau wirkt nur als Fläche blau; mit Weiß gemischt wird es grau, nicht hell.
  - Gelb ist leicht grünstichig – Gelb ¾ + Orange wirkt wärmer und gelber.
  - Reines Orange wirkt ocker – Rot ½ + Orange ist ein kräftiges Orange.
  - Schwarz + Weiß ergibt gleichmäßiges Grau, Rot + Blau ein Violett.
  - Blau und alle Mischungen (auch Gelb, Orange, Grau) nie für Text, Linien
    oder kleine Symbole verwenden – Text nur in Schwarz, Rot, Grün oder Weiß.
  - Schrift auf Rot, Grün, Blau, Violett: Weiß. Auf Gelb, Orange und hellen
    Flächen: Schwarz (siehe ``schrift_auf``).

Die Farbrollen-Logik ist ohne Fremdbibliotheken testbar; nur
``muster_einsetzen`` braucht Pillow und NumPy (wie auf dem Pi installiert).
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


# --- Farbrollen ---

# Rolle → Pigment oder Mischung (Ergebnis des Farbtests)
ROLLEN = {
    "schwarz": "schwarz",
    "weiss": "weiss",
    "rot": "rot",
    "gruen": "gruen",
    "blau": "blau",
    "gelb": "gelb_orange_75",
    "orange": "rot_orange_50",
    "violett": "rot_blau_50",
    "grau": "schwarz_weiss_50",
    "hellgrau": "schwarz_weiss_25",
    "rosa": "rot_weiss_50",
    "apricot": "orange_weiss_50",
    "mint": "gruen_weiss_50",
}

# Rollen, die nur als Fläche taugen – nie für Text, Linien, kleine Symbole.
# Mischungen gehören immer dazu: geglättete Schriftkanten würden sonst farbig.
NUR_FLAECHE = frozenset({"blau"} | {rolle for rolle, name in ROLLEN.items() if name in MISCHUNGEN})

# Lesbare Schriftfarbe je Rolle (auf dem Display geprüft)
SCHRIFT_AUF = {
    "schwarz": "weiss", "weiss": "schwarz", "rot": "weiss", "gruen": "weiss", "blau": "weiss",
    "gelb": "schwarz", "orange": "schwarz", "violett": "weiss", "grau": "schwarz",
    "hellgrau": "schwarz", "rosa": "schwarz", "apricot": "schwarz", "mint": "schwarz",
}


def schrift_auf(rolle):
    """„weiss“ oder „schwarz“ – was auf der Fläche dieser Rolle lesbar ist."""
    return SCHRIFT_AUF.get(rolle, "schwarz")


# --- Platzhalter für Mischungen außerhalb von CSS-Hintergründen ---

# Unauffällige, eindeutige Farben, die in Layouts sonst nicht vorkommen. Sie
# liegen im Farbraum weit auseinander und abseits der Linien zwischen zwei
# Pigmenten, damit geglättete Kanten sich eindeutig zuordnen lassen.
_PLATZHALTER_FARBEN = (
    "#2d69a5", "#d72dd7", "#a569d7", "#d7d7a5", "#69d7d7", "#a52d69", "#69a5d7", "#a5d7d7", "#d7a5d7",
    "#2da5d7", "#d769d7", "#69d7a5", "#69a5a5", "#a52dd7", "#2da569", "#2dd7a5", "#a569a5", "#d7d769",
)

PLATZHALTER = dict(zip(MISCHUNGEN, _PLATZHALTER_FARBEN))


def css_farbe(name, farben):
    """Farbe für ``color``, ``fill``, ``border`` …: Pigment direkt, Mischung als Platzhalter.

    Wer Platzhalter verwendet, muss den Screenshot durch ``muster_einsetzen`` schicken.
    """
    if name in PIGMENTE:
        return farben[name]
    return PLATZHALTER[name]


def rollen_farben(farben):
    """Alle Rollen als CSS-Farbe (Platzhalter für Mischungen)."""
    return {rolle: css_farbe(name, farben) for rolle, name in ROLLEN.items()}


def muster_einsetzen(bild, farben, toleranz=6.0):
    """Ersetzt im Bild alle Platzhalter-Pixel durch das Muster ihrer Mischung.

    Das Muster richtet sich nach der absoluten Pixelposition, so passen
    angrenzende Flächen derselben Mischung nahtlos zusammen.

    Kantenpixel, die der Browser geglättet hat (z. B. schwarze Schrift auf
    gelbem Warnband), liegen auf der Linie zwischen zwei Farben. Jedes solche
    Pixel wird der Linie zugeordnet, auf der es am genauesten liegt: zwischen
    Platzhalter und Pigment wird es der näheren Seite zugeschlagen, zwischen
    zwei Pigmenten bleibt es, wie es ist. So bekommen Schrift und Ränder auf
    Mischflächen keinen Farbsaum.
    """
    import numpy as np
    from PIL import Image

    pixel = np.array(bild.convert("RGB"))
    werte = pixel.astype(np.float32)
    hoehe, breite = pixel.shape[:2]

    vorhanden = []
    for name, platzhalter in PLATZHALTER.items():
        p = np.array(_rgb(platzhalter), dtype=np.float32)
        voll = np.all(werte == p, axis=-1)
        if voll.any():
            vorhanden.append((name, p, voll))
    if not vorhanden:
        return bild

    pigmente = [np.array(_rgb(f), dtype=np.float32) for f in dict.fromkeys(farben.values())]
    zum_muster = [voll.copy() for _, _, voll in vorhanden]

    # Nur Kantenpixel prüfen: weder Pigment noch Platzhalter, höchstens 2 Pixel
    # neben einer Mischfläche. Das sind meist wenige Prozent des Bildes.
    rein = np.zeros((hoehe, breite), dtype=bool)
    for c in pigmente:
        rein |= np.all(werte == c, axis=-1)
    flaeche = np.zeros((hoehe, breite), dtype=bool)
    for _, _, voll in vorhanden:
        flaeche |= voll
    nahe = flaeche.copy()
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            nahe |= np.roll(np.roll(flaeche, dy, axis=0), dx, axis=1)
    kandidaten = np.nonzero(nahe & ~rein & ~flaeche)
    w = werte[kandidaten]

    if len(w):
        def linie(a, b):
            """Abstand jedes Kandidaten zur Strecke a→b und Lage t darauf (0 = a, 1 = b)."""
            d = b - a
            t = np.clip(((w - a) @ d) / float(d @ d), 0.0, 1.0)
            return np.linalg.norm(w - (a + t[:, None] * d), axis=-1), t

        # Beste Erklärung je Pixel: -1 = Kante zwischen zwei Pigmenten (bleibt)
        bester_abstand = np.full(len(w), np.inf, dtype=np.float32)
        beste_wahl = np.full(len(w), -1, dtype=np.int32)
        bestes_t = np.zeros(len(w), dtype=np.float32)
        for i, a in enumerate(pigmente):
            for b in pigmente[i + 1:]:
                abstand, _ = linie(a, b)
                besser = abstand < bester_abstand
                bester_abstand[besser] = abstand[besser]
                beste_wahl[besser] = -1

        wahlen = []
        for k, (_, p, _) in enumerate(vorhanden):
            for c in pigmente:
                abstand, t = linie(c, p)  # t = Anteil des Platzhalters
                besser = abstand < bester_abstand
                bester_abstand[besser] = abstand[besser]
                beste_wahl[besser] = len(wahlen)
                bestes_t[besser] = t[besser]
                wahlen.append((k, c))

        kante = (bester_abstand < toleranz) & (beste_wahl >= 0)
        ys, xs = kandidaten
        for nummer, (k, c) in enumerate(wahlen):
            hier = kante & (beste_wahl == nummer)
            muster_hier = hier & (bestes_t >= 0.5)
            zum_muster[k][ys[muster_hier], xs[muster_hier]] = True
            pigment_hier = hier & (bestes_t < 0.5)
            pixel[ys[pigment_hier], xs[pigment_hier]] = c.astype(pixel.dtype)

    gerade_x = (np.arange(breite) % 2)[None, :]
    gerade_y = (np.arange(hoehe) % 2)[:, None]
    for (name, _, _), maske in zip(vorhanden, zum_muster):
        mischung = MISCHUNGEN[name]
        muster = mischung.pixel()
        nimm_a = np.zeros((hoehe, breite), dtype=bool)
        for y in range(2):
            for x in range(2):
                if muster[y][x] == mischung.a:
                    nimm_a |= (gerade_y == y) & (gerade_x == x)
        pixel[maske & nimm_a] = _rgb(farben[mischung.a])
        pixel[maske & ~nimm_a] = _rgb(farben[mischung.b])
    return Image.fromarray(pixel, "RGB")
