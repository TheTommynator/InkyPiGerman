"""Zifferblätter für einen ruhigen Takt (alle 5, 10 oder 15 Minuten).

Ein 7-Farben-E-Ink-Display braucht für jedes Bild rund 30 Sekunden und kann
keine Teilbereiche neu zeichnen. Diese Zifferblätter zeigen die Zeit deshalb
bewusst in Fünf-Minuten-Schritten (oder mit einem einzigen Zeiger), sodass
sie auch dann stimmen, wenn das Display nur alle paar Minuten neu zeichnet.

Gezeichnet wird mit reinen Farben und ohne Kantenglättung, damit der
Treiber nichts in Punktmuster zerlegen muss. Einzige Ausnahme sind die
offenen Felder im Stundenring: Hellgrau als festes 2×2-Muster (Farbrolle).
"""

import math

from PIL import Image, ImageDraw

from utils.app_utils import get_font
from utils.eink_farben import ROLLEN, css_farbe, muster_einsetzen, palette

from plugins.clock.uhr_worte import (
    WORTUHR_RASTER, datum_text, fuenf_minuten, tageszeit, wortuhr_woerter, zeit_in_worten,
)

SCHWARZ = (0, 0, 0)
WEISS = (255, 255, 255)


# ---------------------------------------------------------------------------
# Zeichnen
# ---------------------------------------------------------------------------

def schrift_fuer(flaeche):
    """Schwarz oder Weiß – was auf dieser Fläche besser lesbar ist."""
    r, g, b = flaeche[:3]
    return SCHWARZ if 0.299 * r + 0.587 * g + 0.114 * b > 150 else WEISS


def _leinwand(dimensionen, hintergrund):
    bild = Image.new("RGB", dimensionen, hintergrund)
    zeichnen = ImageDraw.Draw(bild)
    zeichnen.fontmode = "1"  # keine Kantenglättung: nur reine Farben
    return bild, zeichnen


def _passende_schrift(zeichnen, text, max_breite, max_hoehe, name="Jost", gewicht="bold"):
    groesse = int(max_hoehe)
    while groesse > 8:
        schrift = get_font(name, groesse, gewicht)
        links, oben, rechts, unten = zeichnen.textbbox((0, 0), text, font=schrift)
        if rechts - links <= max_breite and unten - oben <= max_hoehe:
            return schrift
        groesse = int(groesse * 0.92)
    return get_font(name, 8, gewicht)


def zeichne_wortuhr(dimensionen, zeit, akzent, hintergrund):
    """Deutsches Buchstabenraster; die aktuellen Wörter liegen auf Akzentfeldern."""
    b, h = dimensionen
    bild, zeichnen = _leinwand(dimensionen, hintergrund)
    tinte, auf_akzent = schrift_fuer(hintergrund), schrift_fuer(akzent)

    spalten, zeilen = len(WORTUHR_RASTER[0]), len(WORTUHR_RASTER)
    zh = (h * 0.9) / zeilen
    zb = min((b * 0.92) / spalten, zh * 1.3)
    zelle = min(zb, zh)
    x0 = (b - zb * spalten) / 2
    y0 = (h - zh * zeilen) / 2
    schrift = get_font("Jost", int(zelle * 0.62), "bold")
    leise = get_font("Jost", int(zelle * 0.42))
    rand = max(2, int(zelle * 0.08))

    aktiv = set()
    for zeile, spalte, laenge in wortuhr_woerter(zeit.hour, zeit.minute):
        zeichnen.rounded_rectangle(
            [x0 + spalte * zb + rand, y0 + zeile * zh + rand,
             x0 + (spalte + laenge) * zb - rand, y0 + (zeile + 1) * zh - rand],
            radius=int(zelle * 0.2), fill=akzent)
        aktiv.update((zeile, spalte + i) for i in range(laenge))

    for zeile, buchstaben in enumerate(WORTUHR_RASTER):
        for spalte, buchstabe in enumerate(buchstaben):
            mitte = (x0 + (spalte + 0.5) * zb, y0 + (zeile + 0.5) * zh)
            if (zeile, spalte) in aktiv:
                zeichnen.text(mitte, buchstabe, anchor="mm", fill=auf_akzent, font=schrift)
            else:
                # inaktive Buchstaben klein und dünn, damit die Wörter hervortreten
                zeichnen.text(mitte, buchstabe, anchor="mm", fill=tinte, font=leise)
    return bild


def zeichne_worte(dimensionen, zeit, akzent, hintergrund):
    """Große Schrift: „fünf vor halb / vier“, darunter Tageszeit und Datum."""
    b, h = dimensionen
    bild, zeichnen = _leinwand(dimensionen, hintergrund)
    tinte = schrift_fuer(hintergrund)
    rand = int(min(b, h) * 0.08)

    minutenteil, stundenteil = zeit_in_worten(zeit.hour, zeit.minute)
    breite = b - 2 * rand

    oben = _passende_schrift(zeichnen, minutenteil or "x", breite, h * 0.16)
    gross = _passende_schrift(zeichnen, stundenteil, breite, h * 0.3)
    klein = get_font("Jost", max(12, int(h * 0.055)))

    # Datum oben links, Akzentbalken darunter
    zeichnen.text((rand, rand), datum_text(zeit), anchor="lt", fill=tinte, font=klein)
    balken = max(4, int(h * 0.012))
    linie_y = rand + int(h * 0.09)
    zeichnen.rectangle([rand, linie_y, rand + int(breite * 0.18), linie_y + balken], fill=akzent)

    # Hauptzeile(n) im unteren Teil
    y_stunde = h - rand - int(h * 0.13)
    zeichnen.text((rand, y_stunde), stundenteil, anchor="ls", fill=akzent if akzent != hintergrund else tinte,
                  font=gross)
    if minutenteil:
        zeichnen.text((rand, y_stunde - int(h * 0.3)), minutenteil, anchor="ls", fill=tinte, font=oben)
    zeichnen.text((rand, h - rand), tageszeit(zeit.hour), anchor="ls", fill=tinte, font=klein)
    return bild


def _punkt(mitte, radius, winkel):
    """Punkt auf dem Kreis; Winkel in Grad, 0 = zwölf Uhr, im Uhrzeigersinn."""
    rad = math.radians(winkel)
    return mitte[0] + radius * math.sin(rad), mitte[1] - radius * math.cos(rad)


def zeichne_einzeiger(dimensionen, zeit, akzent, hintergrund):
    """Einzeigeruhr: Stundenzeiger auf einem Zifferblatt mit Fünf-Minuten-Strichen."""
    b, h = dimensionen
    bild, zeichnen = _leinwand(dimensionen, hintergrund)
    tinte = schrift_fuer(hintergrund)
    mitte = (b / 2, h / 2)
    r = min(b, h) * 0.46
    staerke = max(2, int(r * 0.012))

    zeichnen.ellipse([mitte[0] - r, mitte[1] - r, mitte[0] + r, mitte[1] + r], outline=tinte, width=staerke * 2)

    # 144 Striche: je Stunde 12 Fünf-Minuten-Schritte, Viertelstunden länger
    for i in range(144):
        winkel = i * 2.5
        if i % 12 == 0:
            laenge, dicke = 0.16, staerke * 3
        elif i % 3 == 0:
            laenge, dicke = 0.09, staerke * 2
        else:
            laenge, dicke = 0.05, staerke
        zeichnen.line([_punkt(mitte, r * 0.94, winkel), _punkt(mitte, r * (0.94 - laenge), winkel)],
                      fill=tinte, width=dicke)

    ziffern = get_font("Jost", int(r * 0.15), "bold")
    for stunde in range(1, 13):
        zeichnen.text(_punkt(mitte, r * 0.62, stunde * 30), str(stunde), anchor="mm", fill=tinte, font=ziffern)

    # ein Zeiger: 30° je Stunde, 0,5° je Minute
    winkel = (zeit.hour % 12) * 30 + zeit.minute * 0.5
    spitze = _punkt(mitte, r * 0.9, winkel)
    ende = _punkt(mitte, r * 0.18, winkel + 180)
    breite = max(6, int(r * 0.035))
    links = _punkt(mitte, breite, winkel - 90)
    rechts = _punkt(mitte, breite, winkel + 90)
    zeichnen.polygon([spitze, links, ende, rechts], fill=akzent)
    knopf = breite * 1.6
    zeichnen.ellipse([mitte[0] - knopf, mitte[1] - knopf, mitte[0] + knopf, mitte[1] + knopf], fill=akzent)
    zeichnen.ellipse([mitte[0] - knopf / 3, mitte[1] - knopf / 3, mitte[0] + knopf / 3, mitte[1] + knopf / 3],
                     fill=hintergrund)
    return bild


def zeichne_stundenring(dimensionen, zeit, akzent, hintergrund, farben=None):
    """Große Stunde in der Mitte, ringsum zwölf Felder für die vergangenen fünf Minuten."""
    farben = farben or palette()
    b, h = dimensionen
    bild, zeichnen = _leinwand(dimensionen, hintergrund)
    tinte = schrift_fuer(hintergrund)
    offen = css_farbe(ROLLEN["hellgrau"], farben)  # Mischung, wird unten als Muster eingesetzt
    mitte = (b / 2, h / 2)
    r_aussen = min(b, h) * 0.46
    r_innen = r_aussen * 0.74
    voll = fuenf_minuten(zeit.minute) // 5

    box = [mitte[0] - r_aussen, mitte[1] - r_aussen, mitte[0] + r_aussen, mitte[1] + r_aussen]
    luecke = 3  # Grad zwischen den Feldern
    for i in range(12):
        start, ende = -90 + i * 30 + luecke / 2, -90 + (i + 1) * 30 - luecke / 2
        zeichnen.pieslice(box, start, ende, fill=akzent if i < voll else offen)
    zeichnen.ellipse([mitte[0] - r_innen, mitte[1] - r_innen, mitte[0] + r_innen, mitte[1] + r_innen],
                     fill=hintergrund)

    # Viertelstunden-Marken innen
    linie = max(3, int(r_aussen * 0.02))
    for winkel in (0, 90, 180, 270):
        zeichnen.line([_punkt(mitte, r_innen * 0.97, winkel), _punkt(mitte, r_innen * 0.87, winkel)],
                      fill=tinte, width=linie)

    stunde = get_font("Jost", int(r_innen * 0.9), "bold")
    zeichnen.text((mitte[0], mitte[1] - r_innen * 0.1), str(zeit.hour), anchor="mm", fill=tinte, font=stunde)
    minutenteil, stundenteil = zeit_in_worten(zeit.hour, zeit.minute)
    text = f"{minutenteil} {stundenteil}".strip()
    klein = _passende_schrift(zeichnen, text, r_innen * 1.3, r_innen * 0.13, gewicht="normal")
    zeichnen.text((mitte[0], mitte[1] + r_innen * 0.52), text, anchor="mm", fill=tinte, font=klein)
    return muster_einsetzen(bild, farben)


# Name des Zifferblatts → Zeichenfunktion (Primärfarbe = Akzent, Sekundärfarbe = Hintergrund)
RUHIGE_UHREN = {
    "Wortuhr": zeichne_wortuhr,
    "Uhrzeit in Worten": zeichne_worte,
    "Einzeigeruhr": zeichne_einzeiger,
    "Stundenring": zeichne_stundenring,
}
