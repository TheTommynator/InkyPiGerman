"""Löschtest: alltagsnahe Bildwechsel, um die Automatik „Altes Bild löschen“ einzustellen.

Jede Szene besteht aus einem Ausgangsbild (wird mit Löschen sauber angezeigt) und
einem Folgebild (wird ohne Löschen darübergezeichnet). Wer auf das Display schaut,
bewertet, ob Reste des Ausgangsbilds zu sehen sind. Aus den Bewertungen und dem
Anteil geänderter Bildpunkte je Szene ergibt sich die Schwelle für die Automatik.

Die Bilder nutzen nur die reinen Pigmente des 7-Farben-Displays, damit nichts
gerastert wird und Reste nicht mit Rastermustern verwechselt werden.
"""

from PIL import Image, ImageDraw

from utils.app_utils import get_font

SCHWARZ, WEISS = (0, 0, 0), (255, 255, 255)
ROT, GRUEN, BLAU = (255, 0, 0), (0, 255, 0), (0, 0, 255)
GELB, ORANGE = (255, 255, 0), (255, 128, 0)

BEWERTUNGEN = ("sauber", "leicht", "stoerend")
MIN_SCHWELLE, MAX_SCHWELLE = 5, 100


# ---------- Zeichnen ----------

class Leinwand:
    """Zeichnet mit Angaben relativ zur Bildgröße (0–1), damit Quer- und Hochformat passen."""

    def __init__(self, groesse, farbe=WEISS):
        self.image = Image.new("RGB", groesse, farbe)
        self.draw = ImageDraw.Draw(self.image)
        self.w, self.h = groesse
        self.einheit = min(self.w, self.h)

    def box(self, x0, y0, x1, y1):
        return (round(x0 * self.w), round(y0 * self.h), round(x1 * self.w) - 1, round(y1 * self.h) - 1)

    def rechteck(self, x0, y0, x1, y1, farbe):
        self.draw.rectangle(self.box(x0, y0, x1, y1), fill=farbe)

    def text(self, x, y, text, groesse, farbe=SCHWARZ, fett=False, anker="la"):
        font = get_font("Jost", max(8, round(groesse * self.einheit)), "bold" if fett else "normal")
        self.draw.text((x * self.w, y * self.h), text, fill=farbe, font=font, anchor=anker)

    def kreis(self, x, y, r, farbe):
        r = r * self.einheit
        cx, cy = x * self.w, y * self.h
        self.draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=farbe)


def _uhr(groesse, zeit):
    c = Leinwand(groesse)
    c.rechteck(0, 0, 1, 0.12, ROT)
    c.text(0.04, 0.06, "Uhr", 0.07, WEISS, fett=True, anker="lm")
    c.text(0.5, 0.48, zeit, 0.42, fett=True, anker="mm")
    c.text(0.5, 0.82, "Sonntag, 11. Oktober", 0.08, anker="mm")
    return c.image


TERMINE = [
    ("08:00", "Frühstück mit Oma", ROT),
    ("10:30", "Zahnarzt", BLAU),
    ("13:00", "Mittagessen", ORANGE),
    ("16:00", "Fußballtraining", GRUEN),
    ("19:30", "Kino", ROT),
]


def _kalender(groesse, termine, zeit):
    c = Leinwand(groesse)
    c.rechteck(0, 0, 1, 0.16, BLAU)
    c.text(0.04, 0.08, "Heute", 0.08, WEISS, fett=True, anker="lm")
    c.text(0.96, 0.08, zeit, 0.08, WEISS, fett=True, anker="rm")
    zeile = 0.84 / max(5, len(termine))
    for i, (uhrzeit, titel, farbe) in enumerate(termine):
        y = 0.16 + i * zeile
        c.rechteck(0.04, y + 0.02, 0.24, y + zeile - 0.02, farbe)
        c.text(0.14, y + zeile / 2, uhrzeit, 0.06, WEISS, fett=True, anker="mm")
        c.text(0.28, y + zeile / 2, titel, 0.065, anker="lm")
    return c.image


def _wetter(groesse, sonnig):
    c = Leinwand(groesse)
    c.rechteck(0, 0, 1, 0.12, ORANGE)
    c.text(0.04, 0.06, "Wetter", 0.07, WEISS, fett=True, anker="lm")
    if sonnig:
        c.kreis(0.22, 0.42, 0.20, ORANGE)
        c.kreis(0.22, 0.42, 0.15, GELB)
        temperatur, text = "18°", "Sonnig"
    else:
        c.kreis(0.16, 0.42, 0.10, BLAU)
        c.kreis(0.26, 0.38, 0.13, BLAU)
        c.kreis(0.33, 0.45, 0.09, BLAU)
        c.rechteck(0.12, 0.42, 0.36, 0.52, BLAU)
        for x in (0.15, 0.22, 0.29):
            c.rechteck(x, 0.56, x + 0.015, 0.64, BLAU)
        temperatur, text = "12°", "Regen"
    c.text(0.70, 0.40, temperatur, 0.30, fett=True, anker="mm")
    c.text(0.70, 0.62, text, 0.08, anker="mm")
    tage = ("Mo", "Di", "Mi", "Do") if sonnig else ("Di", "Mi", "Do", "Fr")
    werte = ("19°", "21°", "17°", "15°") if sonnig else ("11°", "14°", "16°", "18°")
    for i, (tag, wert) in enumerate(zip(tage, werte)):
        x = 0.06 + i * 0.235
        c.rechteck(x, 0.74, x + 0.2, 0.96, GELB if sonnig and i < 2 else WEISS)
        c.text(x + 0.1, 0.80, tag, 0.06, fett=True, anker="mm")
        c.text(x + 0.1, 0.90, wert, 0.06, anker="mm")
    return c.image


def _dunkel(groesse):
    c = Leinwand(groesse, SCHWARZ)
    c.rechteck(0, 0.55, 1, 1, BLAU)
    c.kreis(0.75, 0.30, 0.16, ORANGE)
    c.rechteck(0.05, 0.40, 0.25, 0.85, GRUEN)
    c.rechteck(0.30, 0.25, 0.45, 0.85, ROT)
    c.text(0.5, 0.94, "Urlaubsfoto", 0.06, WEISS, anker="mm")
    return c.image


def _sonnenuntergang(groesse):
    c = Leinwand(groesse, ORANGE)
    c.rechteck(0, 0, 1, 0.22, ROT)
    c.kreis(0.30, 0.50, 0.14, GELB)
    c.rechteck(0, 0.55, 1, 1, BLAU)
    c.rechteck(0.62, 0.48, 0.90, 0.55, SCHWARZ)
    c.text(0.5, 0.94, "Urlaubsfoto", 0.06, WEISS, anker="mm")
    return c.image


def _hell(groesse):
    c = Leinwand(groesse)
    c.text(0.06, 0.10, "Spruch des Tages", 0.07, ROT, fett=True)
    zeilen = ("Wer immer tut, was er schon kann,", "bleibt immer das, was er schon ist.")
    for i, zeile in enumerate(zeilen):
        c.text(0.06, 0.38 + i * 0.13, zeile, 0.065)
    c.text(0.94, 0.86, "– Henry Ford", 0.06, anker="rm")
    return c.image


# ---------- Szenen ----------

SZENEN = [
    {
        "id": "uhr", "name": "Uhrzeit ändert sich",
        "beschreibung": "Eine Uhr springt von 14:59 auf 15:00 – die kleinste typische Änderung.",
        "hinweis": "Schau auf die Ziffern: Sind Umrisse von „14:59“ zu erkennen?",
        "vorher": lambda g: _uhr(g, "14:59"), "nachher": lambda g: _uhr(g, "15:00"),
    },
    {
        "id": "termin", "name": "Neuer Termin",
        "beschreibung": "Im Kalender kommt ein Termin dazu, die Zeilen darunter rutschen nach unten.",
        "hinweis": "Achte auf die Zeilen unter „Zahnarzt“: Ist die alte Schrift noch schwach zu sehen?",
        "vorher": lambda g: _kalender(g, [TERMINE[i] for i in (0, 1, 3, 4)], "09:15"),
        "nachher": lambda g: _kalender(g, TERMINE, "09:20"),
    },
    {
        "id": "wetter", "name": "Wetter ändert sich",
        "beschreibung": "Aus Sonne wird Regen, Temperatur und Vorhersage ändern sich.",
        "hinweis": "Siehst du noch Gelb oder Orange von der Sonne oder die alte Temperatur „18°“?",
        "vorher": lambda g: _wetter(g, True), "nachher": lambda g: _wetter(g, False),
    },
    {
        "id": "ansicht", "name": "Andere Ansicht",
        "beschreibung": "Der Kalender wird durch die Wetter-Ansicht ersetzt, wie beim Wechsel im Zeitplan.",
        "hinweis": "Schau auf die weißen Flächen: Sind die blaue Kopfzeile oder Kalenderzeilen noch zu erahnen?",
        "vorher": lambda g: _kalender(g, TERMINE, "12:00"), "nachher": lambda g: _wetter(g, False),
    },
    {
        "id": "foto", "name": "Foto wechselt",
        "beschreibung": "Ein Urlaubsfoto wird durch ein anderes ersetzt; nur das Meer bleibt gleich.",
        "hinweis": "Schau in den Himmel: Sind die grüne oder rote Fläche des ersten Fotos noch zu erkennen?",
        "vorher": _dunkel, "nachher": _sonnenuntergang,
    },
    {
        "id": "dunkel", "name": "Dunkel zu hell",
        "beschreibung": "Ein dunkles, buntes Foto wird durch eine fast weiße Textseite ersetzt – der härteste Fall.",
        "hinweis": "Auf Weiß bleiben dunkle Reste am ehesten sichtbar: Erkennst du Formen des Fotos?",
        "vorher": _dunkel, "nachher": _hell,
    },
]

SZENEN_IDS = [s["id"] for s in SZENEN]


def szene(szenen_id):
    for s in SZENEN:
        if s["id"] == szenen_id:
            return s
    raise ValueError("Unbekannte Szene.")


def bilder(szenen_id, groesse):
    """(Ausgangsbild, Folgebild) einer Szene in der Größe des Displays."""
    s = szene(szenen_id)
    return s["vorher"](groesse), s["nachher"](groesse)


# ---------- Auswertung ----------

def _runden(prozent):
    return int(round(prozent / 5.0) * 5)


def empfehlung(ergebnisse):
    """Schlägt anhand der Bewertungen Modus und Schwelle vor.

    Args:
        ergebnisse: Liste von {"anteil": Prozent geänderter Bildpunkte, "bewertung": sauber|leicht|stoerend}.

    Gelöscht werden soll ab der kleinsten Änderung, deren Reste gestört haben. Die Schwelle
    liegt zwischen der größten noch akzeptablen Änderung darunter und dieser Änderung.
    """
    bewertet = sorted((e for e in ergebnisse if e.get("bewertung") in BEWERTUNGEN), key=lambda e: e["anteil"])
    if not bewertet:
        return None
    stoerend = [e for e in bewertet if e["bewertung"] == "stoerend"]
    if not stoerend:
        return {
            "modus": "automatisch", "schwelle": MAX_SCHWELLE,
            "text": "Bei keinem Bildwechsel haben Reste gestört. Gelöscht wird nur noch nach einem Neustart "
                    "und einmal am Tag – so ist das Display fast immer doppelt so schnell.",
        }
    grenze = stoerend[0]["anteil"]
    darunter = [e["anteil"] for e in bewertet if e["bewertung"] != "stoerend" and e["anteil"] < grenze]
    if not darunter:
        return {
            "modus": "immer", "schwelle": None,
            "text": "Schon beim kleinsten getesteten Wechsel ({:.0f}\u00a0%) haben Reste gestört. "
                    "Am besten bleibt das Display bei „Immer löschen“.".format(grenze),
        }
    unten = max(darunter)
    schwelle = _runden((unten + grenze) / 2)
    schwelle = max(int(unten) + 1, min(schwelle, int(grenze)), MIN_SCHWELLE)
    text = ("Bis {:.0f}\u00a0% Änderung war das Bild sauber genug, ab {:.0f}\u00a0% haben Reste gestört. "
            "Gelöscht wird deshalb ab {}\u00a0% geänderten Bildpunkten.").format(unten, grenze, schwelle)
    widerspruch = [e for e in bewertet if e["bewertung"] != "stoerend" and e["anteil"] > grenze]
    if widerspruch:
        text += (" Hinweis: Bei einem größeren Wechsel fandest du das Ergebnis in Ordnung – "
                 "zur Sicherheit gilt die vorsichtigere Grenze.")
    return {"modus": "automatisch", "schwelle": schwelle, "text": text}
