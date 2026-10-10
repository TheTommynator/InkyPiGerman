"""Reine Kalender-Logik für das iCloud-Kalender-Plugin.

Bewusst ohne Fremdbibliotheken (kein icalendar, requests, PIL), damit sich
Zeiträume, Tagesaufteilung, Spaltenlayout und die Ansichtsdaten auch in der
GitHub Action ohne Laufzeit-Abhängigkeiten testen lassen.

Alle Zeitangaben sind zeitzonenbehaftete datetime-Objekte. Ganztägige Termine
beginnen um 0:00 Uhr ihres ersten Tages und enden (exklusiv) um 0:00 Uhr nach
ihrem letzten Tag.
"""

import calendar
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

ANSICHTEN = ("tag", "woche", "monat")

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WOCHENTAGE_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]
MONATE_KURZ = ["Jan.", "Feb.", "März", "Apr.", "Mai", "Juni", "Juli",
               "Aug.", "Sept.", "Okt.", "Nov.", "Dez."]

# Kürzeste Dauer, mit der ein Termin im Zeitraster gezeichnet wird
MIN_DAUER_MINUTEN = 30
# Tage, die in der Tagesansicht unter „Demnächst“ erscheinen
VORSCHAU_TAGE = 6


@dataclass
class Termin:
    titel: str
    start: datetime
    ende: datetime
    ganztag: bool
    farbe: str
    kalender: str = ""
    ort: str = ""


def normalisiere_url(url):
    """iCloud teilt Kalender als webcal://-Link, abrufbar ist er per https://."""
    url = (url or "").strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    return url


def parse_stunde(wert, standard):
    try:
        stunde = int(str(wert).strip())
    except (TypeError, ValueError):
        return standard
    return max(0, min(24, stunde))


def tagesbeginn(tag, tz):
    return datetime.combine(tag, time(), tzinfo=tz)


def wochenanfang(tag, wochenstart=0):
    """Erster Tag der Woche, in der `tag` liegt (wochenstart: 0 = Montag … 6 = Sonntag)."""
    return tag - timedelta(days=(tag.weekday() - wochenstart) % 7)


def monatsraster(jahr, monat, wochenstart=0):
    """Vollständige Wochen (Listen von 7 Daten), die den Monat abdecken."""
    erster = date(jahr, monat, 1)
    letzter = date(jahr, monat, calendar.monthrange(jahr, monat)[1])
    tag = wochenanfang(erster, wochenstart)
    wochen = []
    while tag <= letzter:
        wochen.append([tag + timedelta(days=i) for i in range(7)])
        tag += timedelta(days=7)
    return wochen


def zeitraum(ansicht, heute, wochenstart=0):
    """Datumsbereich [von, bis) dessen Termine für die Ansicht geladen werden."""
    if ansicht == "tag":
        return heute, heute + timedelta(days=1 + VORSCHAU_TAGE)
    if ansicht == "woche":
        von = wochenanfang(heute, wochenstart)
        return von, von + timedelta(days=7)
    if ansicht == "monat":
        wochen = monatsraster(heute.year, heute.month, wochenstart)
        return wochen[0][0], wochen[-1][-1] + timedelta(days=1)
    raise ValueError(f"Unbekannte Ansicht: {ansicht}")


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


def spalten_verteilen(segmente, min_dauer=MIN_DAUER_MINUTEN):
    """Verteilt überlappende Termine nebeneinander.

    `segmente` sind (termin, start_min, ende_min). Rückgabe: Liste von
    (termin, start_min, ende_min, spalte, spalten_anzahl) in Eingabereihenfolge
    nach Startzeit. Termine, die sich (auch indirekt) überlappen, bilden eine
    Gruppe und teilen sich deren Breite.
    """
    sortiert = sorted(segmente, key=lambda s: (s[1], -s[2]))
    ergebnis = []
    gruppe = []          # [(segment, spalte)]
    spalten_ende = []    # sichtbares Ende je Spalte der aktuellen Gruppe
    gruppen_ende = None

    def gruppe_abschliessen():
        anzahl = len(spalten_ende)
        for seg, spalte in gruppe:
            ergebnis.append((*seg, spalte, anzahl))

    for seg in sortiert:
        start, ende = seg[1], max(seg[2], seg[1] + min_dauer)
        if gruppen_ende is not None and start >= gruppen_ende:
            gruppe_abschliessen()
            gruppe, spalten_ende, gruppen_ende = [], [], None
        for i, belegt_bis in enumerate(spalten_ende):
            if belegt_bis <= start:
                spalten_ende[i] = ende
                spalte = i
                break
        else:
            spalten_ende.append(ende)
            spalte = len(spalten_ende) - 1
        gruppe.append((seg, spalte))
        gruppen_ende = ende if gruppen_ende is None else max(gruppen_ende, ende)
    if gruppe:
        gruppe_abschliessen()
    return ergebnis


def format_zeit(dt, zeitformat="24h"):
    if zeitformat == "12h":
        stunde = dt.hour % 12 or 12
        suffix = "AM" if dt.hour < 12 else "PM"
        return f"{stunde}:{dt.minute:02d} {suffix}" if dt.minute else f"{stunde} {suffix}"
    return f"{dt.hour}:{dt.minute:02d}"


def format_stunde(stunde, zeitformat="24h"):
    if zeitformat == "12h":
        return f"{stunde % 12 or 12} {'AM' if stunde % 24 < 12 else 'PM'}"
    return f"{stunde}:00"


def datum_lang(tag):
    return f"{tag.day}. {MONATE[tag.month - 1]} {tag.year}"


def tag_bezeichnung(tag, heute):
    if tag == heute:
        return "Heute"
    if tag == heute + timedelta(days=1):
        return "Morgen"
    return f"{WOCHENTAGE[tag.weekday()]}, {tag.day}. {MONATE_KURZ[tag.month - 1]}"


def wochen_titel(tage):
    erster, letzter = tage[0], tage[-1]
    if erster.month == letzter.month:
        bereich = f"{erster.day}.–{letzter.day}. {MONATE[letzter.month - 1]} {letzter.year}"
    elif erster.year == letzter.year:
        bereich = f"{erster.day}. {MONATE_KURZ[erster.month - 1]} – {letzter.day}. {MONATE_KURZ[letzter.month - 1]} {letzter.year}"
    else:
        bereich = f"{datum_lang(erster)} – {datum_lang(letzter)}"
    return bereich


def stundenbereich(segmente_je_tag, von_h, bis_h):
    """Erweitert den eingestellten Stundenbereich, damit kein Termin abgeschnitten wird."""
    if bis_h <= von_h:
        von_h, bis_h = 0, 24
    for segmente in segmente_je_tag:
        for _, start_min, ende_min in segmente:
            ende_min = max(ende_min, start_min + MIN_DAUER_MINUTEN)
            von_h = min(von_h, start_min // 60)
            bis_h = max(bis_h, min(24, math.ceil(ende_min / 60)))
    return von_h, bis_h


def _termin_info(termin, zeitformat):
    return {
        "titel": termin.titel,
        "farbe": termin.farbe,
        "tint": termin_tint(termin.farbe),
        "text": kontrastfarbe(termin.farbe),
        "kalender": termin.kalender,
        "ort": termin.ort,
        "zeit": "" if termin.ganztag else format_zeit(termin.start, zeitformat),
        "zeit_bis": "" if termin.ganztag else format_zeit(termin.ende, zeitformat),
    }


def _zeitraster_spalte(segmente, von_h, bis_h, zeitformat):
    """Positionen (in % der Rasterhöhe) der Termine einer Tagesspalte."""
    gesamt = (bis_h - von_h) * 60
    bloecke = []
    for termin, start_min, ende_min, spalte, anzahl in spalten_verteilen(segmente):
        sichtbar_ende = max(ende_min, start_min + MIN_DAUER_MINUTEN)
        info = _termin_info(termin, zeitformat)
        info.update({
            "oben": (start_min - von_h * 60) / gesamt * 100,
            "hoehe": (sichtbar_ende - start_min) / gesamt * 100,
            "links": spalte / anzahl * 100,
            "breite": 100 / anzahl,
            "minuten": ende_min - start_min,
        })
        bloecke.append(info)
    return bloecke


def _jetzt_position(jetzt, von_h, bis_h):
    minute = jetzt.hour * 60 + jetzt.minute
    if not (von_h * 60 <= minute <= bis_h * 60):
        return None
    return (minute - von_h * 60) / ((bis_h - von_h) * 60) * 100


def _stunden(von_h, bis_h, zeitformat):
    return [{"label": format_stunde(h, zeitformat),
             "oben": (h - von_h) / (bis_h - von_h) * 100}
            for h in range(von_h, bis_h)]


def baue_tag(termine, jetzt, tz, von_h=7, bis_h=21, zeitformat="24h"):
    heute = jetzt.date()
    ganz, zeitlich = termine_am_tag(termine, heute, tz)
    von_h, bis_h = stundenbereich([zeitlich], von_h, bis_h)

    vorschau = []
    for i in range(1, VORSCHAU_TAGE + 1):
        tag = heute + timedelta(days=i)
        g, z = termine_am_tag(termine, tag, tz)
        eintraege = [_termin_info(t, zeitformat) for t in g]
        eintraege += [_termin_info(t, zeitformat) | {"zeit": format_zeit(max(t.start, tagesbeginn(tag, tz)), zeitformat)}
                      for t, _, _ in z]
        if eintraege:
            vorschau.append({"label": tag_bezeichnung(tag, heute), "termine": eintraege})

    return {
        "titel": WOCHENTAGE[heute.weekday()],
        "untertitel": datum_lang(heute),
        "ganztag": [_termin_info(t, zeitformat) for t in ganz],
        "bloecke": _zeitraster_spalte(zeitlich, von_h, bis_h, zeitformat),
        "stunden": _stunden(von_h, bis_h, zeitformat),
        "jetzt": _jetzt_position(jetzt, von_h, bis_h),
        "leer": not ganz and not zeitlich,
        "vorschau": vorschau,
    }


def baue_woche(termine, jetzt, tz, wochenstart=0, von_h=7, bis_h=21,
               zeitformat="24h", wochenende=True):
    heute = jetzt.date()
    start = wochenanfang(heute, wochenstart)
    tage = [start + timedelta(days=i) for i in range(7)]
    if not wochenende:
        tage = [t for t in tage if t.weekday() < 5]

    aufgeteilt = [termine_am_tag(termine, tag, tz) for tag in tage]
    von_h, bis_h = stundenbereich([z for _, z in aufgeteilt], von_h, bis_h)

    spalten = []
    for tag, (ganz, zeitlich) in zip(tage, aufgeteilt):
        spalten.append({
            "kurz": WOCHENTAGE_KURZ[tag.weekday()],
            "nummer": tag.day,
            "heute": tag == heute,
            "vergangen": tag < heute,
            "wochenende": tag.weekday() >= 5,
            "ganztag": [_termin_info(t, zeitformat) for t in ganz],
            "bloecke": _zeitraster_spalte(zeitlich, von_h, bis_h, zeitformat),
        })

    return {
        "titel": f"KW {heute.isocalendar()[1]}",
        "untertitel": wochen_titel(tage),
        "spalten": spalten,
        "hat_ganztag": any(s["ganztag"] for s in spalten),
        "stunden": _stunden(von_h, bis_h, zeitformat),
        "jetzt": _jetzt_position(jetzt, von_h, bis_h) if heute in tage else None,
    }


def baue_monat(termine, jetzt, tz, wochenstart=0, zeitformat="24h", wochenende=True):
    heute = jetzt.date()
    wochen = []
    for woche in monatsraster(heute.year, heute.month, wochenstart):
        if not wochenende:
            woche = [t for t in woche if t.weekday() < 5]
        zellen = []
        for tag in woche:
            ganz, zeitlich = termine_am_tag(termine, tag, tz)
            eintraege = [_termin_info(t, zeitformat) | {"ganztag": True} for t in ganz]
            eintraege += [_termin_info(t, zeitformat) | {
                "ganztag": False,
                "zeit": format_zeit(max(t.start, tagesbeginn(tag, tz)), zeitformat),
            } for t, _, _ in zeitlich]
            zellen.append({
                "nummer": tag.day,
                "heute": tag == heute,
                "anderer_monat": tag.month != heute.month,
                "vergangen": tag < heute,
                "wochenende": tag.weekday() >= 5,
                "termine": eintraege,
            })
        wochen.append(zellen)

    kopf = [WOCHENTAGE_KURZ[(wochenstart + i) % 7] for i in range(7)]
    if not wochenende:
        kopf = [k for k in kopf if k not in ("Sa", "So")]

    return {
        "titel": MONATE[heute.month - 1],
        "untertitel": str(heute.year),
        "kopf": kopf,
        "wochen": wochen,
    }


def hex_zu_rgb(farbe):
    farbe = (farbe or "").lstrip("#")
    if len(farbe) == 3:
        farbe = "".join(c * 2 for c in farbe)
    try:
        return tuple(int(farbe[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return (0, 0, 0)


def kontrastfarbe(farbe):
    """Schwarz oder Weiß – je nachdem, was auf der Farbe besser lesbar ist."""
    r, g, b = hex_zu_rgb(farbe)
    return "#000000" if (r * 299 + g * 587 + b * 114) / 1000 >= 150 else "#ffffff"


# Farben, die 7-Farben-Displays ohne Rastern darstellen. Pimoronis Inky-Bibliothek
# mischt die gesättigte mit der echten Displaypalette (Sättigung 0.5), Waveshare
# rechnet mit den reinen Farben. Weiß fehlt bewusst: ein weißer Termin wäre unsichtbar.
EINK_PALETTEN = {
    "inky": ["#1c181c", "#1dad23", "#1e1dae", "#cd2425", "#e7de23", "#d87b24"],
    "waveshare": ["#000000", "#00ff00", "#0000ff", "#ff0000", "#ffff00", "#ff8000"],
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


def termin_tint(farbe, anteil=0.18):
    """Helle Variante der Kalenderfarbe als Hintergrund für den Stil „Dezent“."""
    r, g, b = hex_zu_rgb(farbe)
    mische = lambda c: round(255 - (255 - c) * anteil)  # noqa: E731
    return "#{:02x}{:02x}{:02x}".format(mische(r), mische(g), mische(b))
