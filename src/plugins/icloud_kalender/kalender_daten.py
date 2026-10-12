"""Reine Kalender-Logik für das iCloud-Kalender-Plugin.

Bewusst ohne Fremdbibliotheken (kein icalendar, requests, PIL), damit sich
Zeiträume, Tagesaufteilung und die Ansichtsdaten auch in der GitHub Action
ohne Laufzeit-Abhängigkeiten testen lassen.

Die Ansichten sind keine klassischen Kalenderraster, sondern auf einen Blick
lesbare Listen in großer Schrift – für alles Weitere gibt es Handy und PC:
  - „Als Nächstes“: der nächste Termin riesig, daneben der Rest von heute und morgen
  - „Wochenzettel“: die nächsten acht Tage als kurze Listen
  - „Tagesblatt“: großes Datum und die Termine von heute

Alle Zeitangaben sind zeitzonenbehaftete datetime-Objekte. Ganztägige Termine
beginnen um 0:00 Uhr ihres ersten Tages und enden (exklusiv) um 0:00 Uhr nach
ihrem letzten Tag.
"""

import math
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from utils.eink_farben import PALETTEN

ANSICHTEN = ("naechstes", "wochenzettel", "tagesblatt")
STANDARD_ANSICHT = "naechstes"
# Frühere Rasteransichten landen bei der neuen Ansicht, die ihnen am nächsten kommt
ALTE_ANSICHTEN = {"tag": "tagesblatt", "woche": "wochenzettel", "monat": "wochenzettel"}

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WOCHENTAGE_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]
MONATE_KURZ = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli",
               "Aug.", "Sept.", "Okt.", "Nov.", "Dez."]

# So viele Tage (ab heute) zeigt der Wochenzettel; so weit schaut „Als Nächstes“ voraus
TAGE = 8


@dataclass
class Termin:
    titel: str
    start: datetime
    ende: datetime
    ganztag: bool
    farbe: str
    kalender: str = ""
    ort: str = ""
    schrift: str = ""  # Schriftfarbe auf der Kalenderfarbe; leer = automatisch


def normalisiere_url(url):
    """iCloud teilt Kalender als webcal://-Link, abrufbar ist er per https://."""
    url = (url or "").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    return url


def ansicht_aus(wert):
    """Gültige Ansicht aus der Einstellung; alte Werte (tag, woche, monat) werden umgedeutet."""
    wert = ALTE_ANSICHTEN.get(wert, wert)
    return wert if wert in ANSICHTEN else STANDARD_ANSICHT


def tagesbeginn(tag, tz):
    return datetime.combine(tag, time(), tzinfo=tz)


def zeitraum(heute):
    """Datumsbereich [von, bis), dessen Termine geladen werden – für alle Ansichten gleich."""
    return heute, heute + timedelta(days=TAGE)


def termine_am_tag(termine, tag, tz):
    """Teilt die Termine eines Tages auf.

    Gibt (ganztaegig, zeitlich) zurück. `zeitlich` enthält Tupel
    (termin, start_minute, ende_minute) – auf den Tag zugeschnitten, sodass ein
    Termin über Mitternacht an beiden Tagen passend erscheint.
    """
    beginn = tagesbeginn(tag, tz)
    ende = tagesbeginn(tag + timedelta(days=1), tz)
    ganztaegig, zeitlich = [], []
    for termin in termine:
        if termin.start >= ende or termin.ende <= beginn:
            # Termine ohne Dauer zählen zu dem Tag, an dem sie beginnen
            if not (termin.start == termin.ende and beginn <= termin.start < ende):
                continue
        if termin.ganztag:
            ganztaegig.append(termin)
            continue
        von = max(termin.start, beginn)
        bis = min(termin.ende, ende)
        start_min = int((von - beginn).total_seconds() // 60)
        ende_min = int(math.ceil((bis - beginn).total_seconds() / 60))
        zeitlich.append((termin, start_min, max(ende_min, start_min)))
    ganztaegig.sort(key=lambda t: (t.start, t.titel.lower()))
    zeitlich.sort(key=lambda s: (s[1], -s[2], s[0].titel.lower()))
    return ganztaegig, zeitlich


def format_zeit(dt, zeitformat="24h"):
    if zeitformat == "12h":
        stunde = dt.hour % 12 or 12
        suffix = "AM" if dt.hour < 12 else "PM"
        return f"{stunde}:{dt.minute:02d} {suffix}" if dt.minute else f"{stunde} {suffix}"
    return f"{dt.hour}:{dt.minute:02d}"


def datum_lang(tag):
    return f"{tag.day}. {MONATE[tag.month - 1]} {tag.year}"


def tag_bezeichnung(tag, heute):
    if tag == heute:
        return "Heute"
    if tag == heute + timedelta(days=1):
        return "Morgen"
    return f"{WOCHENTAGE[tag.weekday()]}, {tag.day}. {MONATE_KURZ[tag.month - 1]}"


def tag_kurz(tag, heute):
    """„heute“, „morgen“, „Sa“ in den nächsten sechs Tagen, sonst „25.10.“."""
    if tag == heute:
        return "heute"
    if tag == heute + timedelta(days=1):
        return "morgen"
    if heute < tag < heute + timedelta(days=7):
        return WOCHENTAGE_KURZ[tag.weekday()]
    return f"{tag.day}.{tag.month}."


def _erster_letzter(termin, tz):
    """Erster und letzter (inklusiver) Tag eines Termins."""
    erster = termin.start.astimezone(tz).date()
    letzter = (max(termin.ende, termin.start + timedelta(seconds=1)) - timedelta(seconds=1)).astimezone(tz).date()
    return erster, letzter


def mehrtaegig(termin, tz):
    erster, letzter = _erster_letzter(termin, tz)
    return letzter > erster


def spanne(termin, heute, tz):
    """Kurztext für mehrtägige Termine: „bis Sa“, „Di–So“, „ab 20.10.“."""
    erster, letzter = _erster_letzter(termin, tz)
    if erster <= heute:
        return f"bis {tag_kurz(letzter, heute)}"
    if letzter < heute + timedelta(days=7):
        return f"{WOCHENTAGE_KURZ[erster.weekday()]}–{WOCHENTAGE_KURZ[letzter.weekday()]}"
    return f"ab {tag_kurz(erster, heute)}"


def countdown(minuten):
    """„in 20 Min.“, „in 1 Std. 20 Min.“"""
    minuten = max(0, int(minuten))
    if minuten < 1:
        return "gleich"
    stunden, rest = divmod(minuten, 60)
    if not stunden:
        return f"in {rest} Min."
    return f"in {stunden} Std." + (f" {rest} Min." if rest else "")


def _zeit_am_tag(termin, tag, tz, zeitformat):
    """Uhrzeit eines Termins an `tag`; leer, wenn er schon am Vortag begonnen hat."""
    return format_zeit(termin.start, zeitformat) if termin.start >= tagesbeginn(tag, tz) else ""


def _eintrag(termin, zeit=""):
    return {"titel": termin.titel, "zeit": zeit, "ort": termin.ort}


def _tagesliste(termine, tag, tz, zeitformat, ohne=(), jetzt=None):
    """Einträge eines Tages: eintägige Ganztagstermine zuerst, dann nach Uhrzeit.
    Mehrtägige Ganztagstermine (Ferien, Urlaub) stehen nicht an jedem Tag, sondern gesondert.
    Mit `jetzt` werden Termine markiert, die schon vorbei sind."""
    ganz, zeitlich = termine_am_tag(termine, tag, tz)
    liste = [_eintrag(t) | {"vorbei": False} for t in ganz if not mehrtaegig(t, tz) and id(t) not in ohne]
    liste += [_eintrag(t, _zeit_am_tag(t, tag, tz, zeitformat))
              | {"vorbei": jetzt is not None and t.start < t.ende <= jetzt}
              for t, _, _ in zeitlich if id(t) not in ohne]
    return liste


def _ganztag_heute(termine, heute, tz):
    """Ganztägige Termine, die heute stattfinden – mehrtägige mit „bis …“."""
    ganz, _ = termine_am_tag(termine, heute, tz)
    return [{"titel": t.titel, "spanne": spanne(t, heute, tz) if mehrtaegig(t, tz) else ""} for t in ganz]


def baue_naechstes(termine, jetzt, tz, zeitformat="24h"):
    """„Als Nächstes“: der nächste (oder laufende) Termin groß, daneben der Rest
    von heute und morgen, unten ein kurzer Ausblick auf die Woche."""
    heute = jetzt.date()
    morgen = heute + timedelta(days=1)
    grenze = tagesbeginn(heute + timedelta(days=TAGE), tz)
    kandidaten = sorted(
        (t for t in termine if not t.ganztag and t.start < grenze
         and (t.start > jetzt or t.start <= jetzt < t.ende)),
        key=lambda t: (t.start, t.titel.lower()))

    held = None
    if kandidaten:
        t = kandidaten[0]
        start_tag = t.start.astimezone(tz).date()
        laeuft = t.start <= jetzt
        if laeuft:
            ende_tag = t.ende.astimezone(tz).date()
            bis = format_zeit(t.ende, zeitformat) if ende_tag == heute else tag_kurz(ende_tag, heute)
            label, wann = "Läuft gerade", f"noch bis {bis}"
        elif start_tag == heute:
            label, wann = "Als Nächstes", countdown((t.start - jetzt).total_seconds() / 60)
        else:
            label, wann = "Als Nächstes", tag_bezeichnung(start_tag, heute)
        held = _eintrag(t, format_zeit(t.start, zeitformat)) | {"label": label, "wann": wann, "laeuft": laeuft}

    ohne = {id(kandidaten[0])} if kandidaten else set()
    morgen_beginn = tagesbeginn(morgen, tz)
    spaeter = [_eintrag(t, format_zeit(t.start, zeitformat)) for t in kandidaten[1:] if t.start < morgen_beginn]

    # Ausblick ab übermorgen: je Tag die Einträge; mehrtägige erscheinen einmal mit Spanne
    morgen_ganz, morgen_zeitlich = termine_am_tag(termine, morgen, tz)
    gezeigt = {id(t) for t in termine_am_tag(termine, heute, tz)[0] + morgen_ganz}
    gezeigt |= {id(t) for t, _, _ in morgen_zeitlich} | ohne
    ausblick = []
    for i in range(2, 7):
        tag = heute + timedelta(days=i)
        ganz, zeitlich = termine_am_tag(termine, tag, tz)
        titel = []
        for t in ganz + [t for t, _, _ in zeitlich]:
            if id(t) in gezeigt:
                continue
            gezeigt.add(id(t))
            if t.ganztag and mehrtaegig(t, tz):
                titel.append(f"{t.titel} bis {tag_kurz(_erster_letzter(t, tz)[1], heute)}")
            else:
                titel.append(t.titel)
        if titel:
            ausblick.append({"tag": WOCHENTAGE_KURZ[tag.weekday()], "titel": titel})

    return {
        "wochentag": WOCHENTAGE[heute.weekday()],
        "datum": f"{heute.day}. {MONATE[heute.month - 1]}",
        "ganztag": _ganztag_heute(termine, heute, tz),
        "held": held,
        "held_heute": bool(kandidaten) and kandidaten[0].start < morgen_beginn,
        "spaeter": spaeter,
        "morgen": [_eintrag(t) for t in termine_am_tag(termine, morgen, tz)[0]
                   if mehrtaegig(t, tz) and t.start >= morgen_beginn]
        + _tagesliste(termine, morgen, tz, zeitformat, ohne),
        "ausblick": ausblick,
    }


def baue_wochenzettel(termine, jetzt, tz, zeitformat="24h", tage=TAGE):
    """„Wochenzettel“: die nächsten Tage ab heute als kurze Listen.
    Mehrtägige Ganztagstermine stehen einmal in einer Zeile darüber."""
    heute = jetzt.date()
    letzter_tag = heute + timedelta(days=tage - 1)
    beginn, ende = tagesbeginn(heute, tz), tagesbeginn(letzter_tag + timedelta(days=1), tz)
    band = sorted((t for t in termine if t.ganztag and mehrtaegig(t, tz) and t.start < ende and t.ende > beginn),
                  key=lambda t: (t.start, t.titel.lower()))

    spalten = []
    for i in range(tage):
        tag = heute + timedelta(days=i)
        # Was heute schon vorbei ist, wird durchgestrichen
        liste = _tagesliste(termine, tag, tz, zeitformat, jetzt=jetzt if tag == heute else None)
        spalten.append({
            "kurz": WOCHENTAGE_KURZ[tag.weekday()],
            "nummer": f"{tag.day}.",
            "heute": tag == heute,
            "wochenende": tag.weekday() >= 5,
            "termine": liste,
        })

    if heute.month == letzter_tag.month:
        bereich = f"{heute.day}.–{letzter_tag.day}. {MONATE[heute.month - 1]}"
    else:
        bereich = f"{heute.day}. {MONATE_KURZ[heute.month - 1]} – {letzter_tag.day}. {MONATE_KURZ[letzter_tag.month - 1]}"
    return {
        "titel": "Diese Woche",
        "bereich": bereich,
        "kw": heute.isocalendar()[1],
        "band": [{"titel": t.titel, "spanne": spanne(t, heute, tz)} for t in band],
        "tage": spalten,
    }


def baue_tagesblatt(termine, jetzt, tz, zeitformat="24h"):
    """„Tagesblatt“: großes Datum, die Termine von heute und eine Zeile für morgen."""
    heute = jetzt.date()
    morgen = heute + timedelta(days=1)
    _, zeitlich = termine_am_tag(termine, heute, tz)
    liste, naechst_gefunden = [], False
    for t, _, _ in zeitlich:
        laeuft = t.start <= jetzt < t.ende
        vorbei = t.ende <= jetzt and not laeuft
        naechst = not vorbei and not naechst_gefunden
        naechst_gefunden |= naechst
        liste.append(_eintrag(t, _zeit_am_tag(t, heute, tz, zeitformat))
                     | {"vorbei": vorbei, "laeuft": laeuft, "naechst": naechst})

    morgen_ganz, morgen_zeitlich = termine_am_tag(termine, morgen, tz)
    morgen_liste = [t.titel for t in morgen_ganz if t.start >= tagesbeginn(morgen, tz)]
    morgen_liste += [f"{format_zeit(t.start, zeitformat)} {t.titel}" if z else t.titel
                     for t, z in ((t, t.start >= tagesbeginn(morgen, tz)) for t, _, _ in morgen_zeitlich)]
    return {
        "wochentag": WOCHENTAGE[heute.weekday()],
        "nummer": heute.day,
        "monat": MONATE[heute.month - 1],
        "ganztag": _ganztag_heute(termine, heute, tz),
        "termine": liste,
        "morgen": morgen_liste,
    }


def hex_zu_rgb(farbe):
    farbe = (farbe or "").lstrip("#")
    if len(farbe) == 3:
        farbe = "".join(c * 2 for c in farbe)
    try:
        return tuple(int(farbe[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return (0, 0, 0)


# Farben, die 7-Farben-Displays ohne Rastern darstellen. Pimoronis Inky-Bibliothek
# mischt die gesättigte mit der echten Displaypalette (Sättigung 0.5), Waveshare
# rechnet mit den reinen Farben. Weiß fehlt bewusst: ein weißer Termin wäre unsichtbar.
# Pigmentfarben ohne Weiß, in fester Reihenfolge (Quelle: utils/eink_farben.py)
EINK_PALETTEN = {
    name: [farben[p] for p in ("schwarz", "gruen", "blau", "rot", "gelb", "orange")]
    for name, farben in PALETTEN.items()
}


def eink_palette(display_type):
    return EINK_PALETTEN["inky" if str(display_type).startswith("inky") else "waveshare"]


def naechste_farbe(farbe, palette):
    """Die Palettenfarbe, die `farbe` am ähnlichsten ist (gewichteter RGB-Abstand)."""
    r, g, b = hex_zu_rgb(farbe)

    def abstand(kandidat):
        r2, g2, b2 = hex_zu_rgb(kandidat)
        return 3 * (r - r2) ** 2 + 4 * (g - g2) ** 2 + 2 * (b - b2) ** 2

    return min(palette, key=abstand)
