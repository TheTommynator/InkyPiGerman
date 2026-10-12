"""Löschtest: alltagsnahe Abläufe, um die Automatik „Altes Bild löschen“ einzustellen.

Reste alter Bilder entstehen auf dem Display selten durch einen einzelnen Wechsel,
sondern sammeln sich an: Die Uhr springt jede Minute weiter, der Kalender ändert
sich über den Tag, Ansichten wechseln sich ab. Jeder Ablauf beginnt deshalb mit
einem sauberen Bild (mit Löschen) und zeigt dann mehrere Bilder hintereinander
ohne Löschen. Nach jedem Bild sagt man, ob schon störende Reste zu sehen sind.

Gemessen wird genauso wie in der Automatik (display/loeschen.py): wie viele Bilder
seit dem Löschen kamen und welcher Anteil der Fläche sich seitdem verändert hat.
Daraus ergeben sich die beiden Grenzen der Automatik.

Die Bilder nutzen die Farbrollen aus dem Farbtest – reine Pigmente und
Mischungen im 2×2-Muster, wie die Plugins.
"""

from PIL import Image, ImageDraw

from display import loeschen
from utils import eink_farben
from utils.app_utils import get_font

FARBEN = eink_farben.palette("waveshare")
ROLLEN = eink_farben.rollen_farben(FARBEN)

BEWERTUNGEN = ("sauber", "leicht", "stoerend")


# ---------- Zeichnen ----------

class Leinwand:
    """Zeichnet mit Angaben relativ zur Bildgröße (0–1), damit Quer- und Hochformat passen.

    Farben sind Rollen (z. B. „gelb“, „hellgrau“); Mischungen werden zuerst als
    Platzhalter gezeichnet und in ``fertig`` durch ihr Muster ersetzt.
    """

    def __init__(self, groesse, farbe="weiss"):
        self.image = Image.new("RGB", groesse, ROLLEN[farbe])
        self.draw = ImageDraw.Draw(self.image)
        self.w, self.h = groesse
        self.einheit = min(self.w, self.h)

    def box(self, x0, y0, x1, y1):
        return (round(x0 * self.w), round(y0 * self.h), round(x1 * self.w) - 1, round(y1 * self.h) - 1)

    def rechteck(self, x0, y0, x1, y1, farbe):
        self.draw.rectangle(self.box(x0, y0, x1, y1), fill=ROLLEN[farbe])

    def text(self, x, y, text, groesse, farbe="schwarz", fett=False, anker="la"):
        font = get_font("Jost", max(8, round(groesse * self.einheit)), "bold" if fett else "normal")
        self.draw.text((x * self.w, y * self.h), text, fill=ROLLEN[farbe], font=font, anchor=anker)

    def kreis(self, x, y, r, farbe, rand=None, breite=0):
        r = r * self.einheit
        cx, cy = x * self.w, y * self.h
        self.draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ROLLEN[farbe] if farbe else None,
                          outline=ROLLEN[rand] if rand else None, width=round(breite * self.einheit))

    def linie(self, x0, y0, x1, y1, farbe, breite):
        self.draw.line((x0 * self.w, y0 * self.h, x1 * self.w, y1 * self.h), fill=ROLLEN[farbe],
                       width=max(1, round(breite * self.einheit)))

    def fertig(self):
        return eink_farben.muster_einsetzen(self.image, FARBEN)


def _uhr(groesse, stunde, minute):
    """Analoge Uhr mit Zeigern und Digitalzeit, wie das Uhr-Plugin im Minutentakt."""
    import math
    c = Leinwand(groesse)
    quer = c.w >= c.h
    cx, cy = (0.28, 0.5) if quer else (0.5, 0.32)
    r = 0.40
    radius_x = r * c.einheit / c.w
    radius_y = r * c.einheit / c.h
    c.kreis(cx, cy, r, "apricot", rand="schwarz", breite=0.015)
    for i in range(12):
        winkel = math.radians(i * 30)
        innen = 0.85 if i % 3 else 0.75
        c.linie(cx + math.sin(winkel) * radius_x * innen, cy - math.cos(winkel) * radius_y * innen,
                cx + math.sin(winkel) * radius_x * 0.95, cy - math.cos(winkel) * radius_y * 0.95,
                "schwarz", 0.012)
    stunden_winkel = math.radians((stunde % 12 + minute / 60) * 30)
    minuten_winkel = math.radians(minute * 6)
    c.linie(cx, cy, cx + math.sin(stunden_winkel) * radius_x * 0.55, cy - math.cos(stunden_winkel) * radius_y * 0.55,
            "schwarz", 0.035)
    c.linie(cx, cy, cx + math.sin(minuten_winkel) * radius_x * 0.85, cy - math.cos(minuten_winkel) * radius_y * 0.85,
            "rot", 0.02)
    c.kreis(cx, cy, 0.03, "schwarz")
    tx, ty = (0.75, 0.42) if quer else (0.5, 0.74)
    c.text(tx, ty, f"{stunde:02d}:{minute:02d}", 0.22, fett=True, anker="mm")
    c.text(tx, ty + (0.2 if quer else 0.1), "Montag, 12. Oktober", 0.06, anker="mm")
    return c.fertig()


TERMINE = [
    (8, 0, 9, 0, "Frühstück mit Oma", "rot"),
    (10, 30, 11, 30, "Zahnarzt", "blau"),
    (13, 0, 14, 0, "Mittagessen", "orange"),
    (16, 0, 17, 30, "Fußballtraining", "gruen"),
    (19, 30, 22, 0, "Kino", "violett"),
]
NEUER_TERMIN = (14, 30, 15, 0, "Paket abholen", "rot")


def _kalender(groesse, stunde, minute, mit_neuem=False):
    """Tagesliste: vergangene Termine grau, der laufende gelb hinterlegt, wie im Kalender-Plugin."""
    c = Leinwand(groesse)
    termine = sorted(TERMINE + ([NEUER_TERMIN] if mit_neuem else []))
    jetzt = stunde * 60 + minute
    c.rechteck(0, 0, 1, 0.15, "blau")
    c.text(0.04, 0.075, "Heute", 0.08, "weiss", fett=True, anker="lm")
    c.text(0.96, 0.075, f"{stunde:02d}:{minute:02d}", 0.08, "weiss", fett=True, anker="rm")
    zeile = 0.85 / 6
    for i, (h0, m0, h1, m1, titel, farbe) in enumerate(termine):
        y = 0.15 + i * zeile
        beginn, ende = h0 * 60 + m0, h1 * 60 + m1
        if ende <= jetzt:
            c.rechteck(0, y, 1, y + zeile, "hellgrau")
        elif beginn <= jetzt:
            c.rechteck(0, y, 1, y + zeile, "gelb")
        c.rechteck(0.03, y + 0.02, 0.22, y + zeile - 0.02, farbe)
        c.text(0.125, y + zeile / 2, f"{h0:02d}:{m0:02d}", 0.055, eink_farben.schrift_auf(farbe), fett=True, anker="mm")
        c.text(0.26, y + zeile / 2, titel, 0.06, anker="lm")
    return c.fertig()


def _wetter(groesse, sonnig):
    c = Leinwand(groesse)
    c.rechteck(0, 0, 1, 0.13, "orange")
    c.text(0.04, 0.065, "Wetter", 0.07, fett=True, anker="lm")
    if sonnig:
        c.rechteck(0, 0.13, 1, 0.68, "mint")
        c.kreis(0.22, 0.40, 0.17, "orange")
        c.kreis(0.22, 0.40, 0.13, "gelb")
        temperatur, text = "18°", "Sonnig"
    else:
        c.rechteck(0, 0.13, 1, 0.68, "grau")
        c.kreis(0.16, 0.42, 0.10, "blau")
        c.kreis(0.26, 0.37, 0.13, "blau")
        c.kreis(0.33, 0.45, 0.09, "blau")
        c.rechteck(0.12, 0.42, 0.36, 0.52, "blau")
        temperatur, text = "12°", "Regen"
    c.text(0.70, 0.36, temperatur, 0.26, fett=True, anker="mm")
    c.text(0.70, 0.58, text, 0.08, anker="mm")
    tage = ("Di", "Mi", "Do", "Fr")
    werte = ("19°", "21°", "17°", "15°") if sonnig else ("11°", "14°", "16°", "18°")
    for i, (tag, wert) in enumerate(zip(tage, werte)):
        x = 0.04 + i * 0.24
        c.rechteck(x, 0.72, x + 0.21, 0.96, "gelb" if sonnig else "rosa")
        c.text(x + 0.105, 0.79, tag, 0.06, fett=True, anker="mm")
        c.text(x + 0.105, 0.89, wert, 0.06, anker="mm")
    return c.fertig()


def _foto(groesse):
    c = Leinwand(groesse, "schwarz")
    c.rechteck(0, 0, 1, 0.55, "violett")
    c.rechteck(0, 0.55, 1, 1, "blau")
    c.kreis(0.75, 0.30, 0.16, "orange")
    c.rechteck(0.05, 0.40, 0.25, 0.85, "gruen")
    c.rechteck(0.30, 0.25, 0.45, 0.85, "schwarz")
    c.text(0.5, 0.94, "Urlaubsfoto", 0.06, "weiss", anker="mm")
    return c.fertig()


def _spruch(groesse):
    c = Leinwand(groesse)
    c.text(0.06, 0.10, "Spruch des Tages", 0.07, "rot", fett=True)
    zeilen = ("Wer immer tut, was er schon kann,", "bleibt immer das, was er schon ist.")
    for i, zeile in enumerate(zeilen):
        c.text(0.06, 0.38 + i * 0.13, zeile, 0.065)
    c.text(0.94, 0.86, "– Henry Ford", 0.06, anker="rm")
    return c.fertig()


# ---------- Abläufe ----------

def _uhr_bilder():
    return [lambda g, m=m: _uhr(g, 10, m) for m in range(0, 13)]


def _tag_bilder():
    zeiten = [(7, 30, False), (8, 30, False), (9, 15, False), (10, 45, False), (12, 0, True),
              (13, 30, True), (15, 0, True), (16, 45, True), (18, 0, True)]
    return [lambda g, h=h, m=m, n=n: _kalender(g, h, m, n) for h, m, n in zeiten]


def _wechsel_bilder():
    return [
        lambda g: _kalender(g, 12, 0, True),
        lambda g: _wetter(g, True),
        _foto,
        lambda g: _uhr(g, 12, 30),
        _spruch,
        lambda g: _wetter(g, False),
        lambda g: _kalender(g, 13, 30, True),
        _foto,
    ]


ABLAEUFE = [
    {
        "id": "uhr", "name": "Uhr im Minutentakt",
        "beschreibung": "Eine Uhr mit Zeigern und Ziffern springt Minute für Minute weiter – wie mit „Jede Minute“. "
                        "Viele kleine Wechsel an denselben Stellen.",
        "hinweis": "Schau auf die alten Zeigerstellungen und die Ziffern: Sind Schatten früherer Minuten zu sehen?",
        "bilder": _uhr_bilder(),
    },
    {
        "id": "tag", "name": "Kalender über den Tag",
        "beschreibung": "Der Tag schreitet voran: Termine werden grau, der laufende ist gelb hinterlegt, "
                        "mittags kommt ein Termin dazu und die Zeilen rutschen.",
        "hinweis": "Schau auf die Zeilen: Sind alte Hinterlegungen oder verrutschte Schrift noch zu erahnen?",
        "bilder": _tag_bilder(),
    },
    {
        "id": "wechsel", "name": "Ansichten im Wechsel",
        "beschreibung": "Kalender, Wetter, Foto, Uhr und Spruch wechseln sich ab, wie im Zeitplan.",
        "hinweis": "Auf hellen Flächen bleiben dunkle Reste am ehesten sichtbar: Erkennst du Formen früherer Ansichten?",
        "bilder": _wechsel_bilder(),
    },
]

ABLAUF_IDS = [a["id"] for a in ABLAEUFE]


def ablauf(ablauf_id):
    for a in ABLAEUFE:
        if a["id"] == ablauf_id:
            return a
    raise ValueError("Unbekannter Ablauf.")


def schritte(ablauf_id):
    """Anzahl der Bilder ohne Löschen (nach dem sauberen Ausgangsbild)."""
    return len(ablauf(ablauf_id)["bilder"]) - 1


def bild(ablauf_id, schritt, groesse):
    """Bild `schritt` eines Ablaufs (0 = sauberes Ausgangsbild)."""
    bilder = ablauf(ablauf_id)["bilder"]
    if not 0 <= schritt < len(bilder):
        raise ValueError("Unbekannter Schritt.")
    return bilder[schritt](groesse)


# Verkleinerte Vergleichsbilder, damit nicht jeder Schritt alle vorigen Bilder neu zeichnet
_pigment_cache = {}


def pigmente(ablauf_id, schritt, groesse, fertiges_bild=None):
    key = (ablauf_id, schritt, tuple(groesse))
    if key not in _pigment_cache:
        _pigment_cache[key] = loeschen.pigment_bild(fertiges_bild or bild(ablauf_id, schritt, groesse))
    return _pigment_cache[key]


def verlauf_bis(ablauf_id, schritt, groesse, fertiges_bild=None):
    """Verlauf wie in der Automatik, nachdem die Bilder 0…schritt gezeigt wurden (0 mit Löschen).

    `fertiges_bild` ist Bild `schritt`, falls es schon gezeichnet wurde.
    """
    verlauf = loeschen.Verlauf()
    for i in range(schritt + 1):
        vorhanden = fertiges_bild if i == schritt else None
        verlauf.merken(pigmente(ablauf_id, i, groesse, vorhanden), geloescht=(i == 0))
    return verlauf


def flaeche(verlauf):
    """Anteil der Fläche in Prozent, der sich seit dem Löschen verändert hat."""
    if verlauf.maske is None:
        return 0.0
    return round(100 * sum(verlauf.maske) / max(1, len(verlauf.maske)), 1)


# ---------- Auswertung ----------

def _runden(prozent):
    return int(round(prozent / 5.0) * 5)


def empfehlung(ergebnisse):
    """Schlägt anhand der Bewertungen Modus und die beiden Grenzen der Automatik vor.

    Args:
        ergebnisse: Liste von {"ablauf", "bilder" (Bilder ohne Löschen), "flaeche" (Prozent),
            "bewertung" (sauber|leicht|stoerend)}.

    1. Höchstzahl der Bilder ohne Löschen: aus dem Uhr-Ablauf (kleine Wechsel an denselben
       Stellen) – ein Bild weniger als beim ersten störenden.
    2. Flächen-Schwelle: aus allen Bewertungen, die unterhalb dieser Höchstzahl liegen –
       zwischen der größten noch sauberen und der kleinsten störenden veränderten Fläche.
    """
    bewertet = [e for e in ergebnisse if e.get("bewertung") in BEWERTUNGEN]
    if not bewertet:
        return None

    uhr = sorted((e for e in bewertet if e.get("ablauf") == "uhr"), key=lambda e: e["bilder"])
    uhr_stoerend = [e for e in uhr if e["bewertung"] == "stoerend"]
    if uhr_stoerend:
        max_bilder = uhr_stoerend[0]["bilder"] - 1
    else:
        # Ohne störende Reste: so viele Bilder wie getestet, sonst der Standard
        max_bilder = max([e["bilder"] for e in uhr] or [loeschen.STANDARD_MAX_BILDER])
    if max_bilder < 1:
        return {"modus": "immer", "schwelle": None, "max_bilder": None,
                "text": "Schon nach einem Bild ohne Löschen haben Reste gestört. "
                        "Am besten bleibt das Display bei „Immer löschen“."}

    relevant = sorted((e for e in bewertet if e["bilder"] <= max_bilder), key=lambda e: e["flaeche"])
    stoerend = [e for e in relevant if e["bewertung"] == "stoerend"]
    if stoerend:
        grenze = stoerend[0]["flaeche"]
        darunter = [e["flaeche"] for e in relevant if e["bewertung"] != "stoerend" and e["flaeche"] < grenze]
        if darunter:
            unten = max(darunter)
            schwelle = max(int(unten) + 1, min(_runden((unten + grenze) / 2), int(grenze)))
        else:
            schwelle = int(grenze)
        schwelle = max(loeschen.MIN_SCHWELLE, min(loeschen.MAX_SCHWELLE, schwelle))
        flaeche_text = f"sobald sich seit dem letzten Löschen {schwelle} % der Fläche verändert haben"
    else:
        schwelle = loeschen.MAX_SCHWELLE
        flaeche_text = None

    if schwelle <= loeschen.MIN_SCHWELLE and max_bilder <= 1:
        return {"modus": "immer", "schwelle": None, "max_bilder": None,
                "text": "Reste haben fast sofort gestört. Am besten bleibt das Display bei „Immer löschen“."}

    teile = [f"spätestens nach {max_bilder} {'Bild' if max_bilder == 1 else 'Bildern'} ohne Löschen"]
    if flaeche_text:
        teile.append(flaeche_text)
    text = "Gelöscht wird " + " oder ".join(teile) + " – und wie bisher einmal am Tag."
    if not uhr:
        text += " Den Uhr-Ablauf hast du nicht bewertet, die Höchstzahl ist deshalb nur ein Richtwert."
    elif not uhr_stoerend:
        text += (f" Bei der Uhr haben auch nach {max_bilder} Bildern keine Reste gestört; "
                 "länger konnte der Test nicht prüfen.")
    return {"modus": "automatisch", "schwelle": schwelle, "max_bilder": max_bilder, "text": text}
