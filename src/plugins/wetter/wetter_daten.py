"""Reine Wetter-Logik für das Plugin „Wetter“.

Bewusst ohne Fremdbibliotheken (kein requests, PIL), damit sich Auswertung,
Satz des Tages, Stundenstreifen und Temperaturbalken in der GitHub Action
ohne Laufzeit-Abhängigkeiten testen lassen.

Datenquellen:
  - Open-Meteo (Vorhersage; für Deutschland rechnet Open-Meteo automatisch mit
    den DWD-Modellen ICON-D2 und ICON-EU)
  - Bright Sky (amtliche Warnungen des Deutschen Wetterdienstes)
Beide brauchen keinen API-Schlüssel.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

ANSICHTEN = ("heute", "woche", "beides", "fenster", "poesie")
# Ansichten, die eher Bild als Datenanzeige sind (siehe kunst_daten.py)
KUNST_ANSICHTEN = ("fenster", "poesie")
DETAILS = ("gefuehlt", "wind", "regen", "uv", "feuchte", "sonne")
STANDARD_DETAILS = ("wind", "regen", "uv")
MAX_DETAILS = 3

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WOCHENTAGE_KURZ = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]
# Geschütztes Leerzeichen: „15 Uhr“ wird nie getrennt
NBSP = "\u00a0"
HIMMELSRICHTUNGEN = ["N", "NO", "O", "SO", "S", "SW", "W", "NW"]

# Stundenstreifen: „Jetzt“ und danach alle 2 Stunden, zusammen 12 Stunden
STUNDEN_SCHRITT = 2
STUNDEN_FELDER = 7
# Ab dieser Menge (mm pro Stunde) zählt eine Stunde als nass
REGEN_SCHWELLE = 0.2
# Volle Höhe des Regenbalkens im Stundenstreifen (mm pro 2 Stunden)
REGEN_SKALA_MM = 4.0
# Regenwahrscheinlichkeit, ab der sie in der Tagesliste erscheint
REGEN_PROZENT_AB = 20

# Temperaturfarbe (Stil „farbig“): unter 8° blau, unter 22° orange, sonst rot
KALT_BIS = 8
WARM_AB = 22


# --- Wettercodes (WMO, wie von Open-Meteo geliefert) ---

def wetterart(code):
    """Grobe Art des Wetters zu einem WMO-Code."""
    code = int(code or 0)
    if code == 0:
        return "sonne"
    if code == 1:
        return "heiter"
    if code == 2:
        return "wolkig"
    if code == 3:
        return "bedeckt"
    if code in (45, 48):
        return "nebel"
    if 51 <= code <= 67:
        return "regen"
    if 71 <= code <= 77 or code in (85, 86):
        return "schnee"
    if 80 <= code <= 82:
        return "schauer"
    if code >= 95:
        return "gewitter"
    return "wolkig"


# Reihenfolge, nach der in einem 2-Stunden-Feld das „wichtigste“ Wetter gewinnt
GEWICHT = {"sonne": 0, "heiter": 1, "wolkig": 2, "bedeckt": 3, "nebel": 4,
           "schauer": 5, "regen": 6, "schnee": 7, "gewitter": 8}

NASS = {"regen", "schauer", "schnee", "gewitter"}


def icon_name(code, tag=True):
    """Name des Icons; nachts wird aus Sonne der Mond."""
    art = wetterart(code)
    if not tag:
        if art == "sonne":
            return "mond"
        if art == "heiter":
            return "mond_wolke"
        if art == "schauer":
            return "regen"
    return art


def wetterwort(code):
    """Kurzes Wort für den Satz des Tages („Morgen sonnig …“)."""
    return {
        "sonne": "sonnig", "heiter": "freundlich", "wolkig": "wolkig",
        "bedeckt": "trüb", "nebel": "neblig", "regen": "regnerisch",
        "schauer": "mit Schauern", "schnee": "mit Schnee", "gewitter": "gewittrig",
    }[wetterart(code)]


# --- Hilfen ---

def zahl(wert, standard=0.0):
    try:
        return float(wert) if wert is not None else standard
    except (TypeError, ValueError):
        return standard


def grad(wert):
    """Ganze Grad ohne „-0“."""
    gerundet = round(zahl(wert))
    return 0 if gerundet == 0 else gerundet


def mm_text(wert):
    wert = zahl(wert)
    if wert < 0.1:
        return ""
    text = f"{wert:.1f}" if wert < 10 else f"{wert:.0f}"
    return text.replace(".", ",") + " mm"


def himmelsrichtung(grad_wert):
    return HIMMELSRICHTUNGEN[round(zahl(grad_wert) / 45) % 8]


def uhrzeit(dt):
    return f"{dt.hour}:{dt.minute:02d}"


def datum_text(tag):
    return f"{WOCHENTAGE[tag.weekday()]}, {tag.day}. {MONATE[tag.month - 1]}"


def parse_zeit(text, tz):
    """Open-Meteo liefert Ortszeit ohne Zeitzone (dank timezone=…), Bright Sky mit."""
    dt = datetime.fromisoformat(str(text))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


# --- Auswertung der Open-Meteo-Antwort ---

@dataclass
class Stunde:
    zeit: datetime
    temp: float
    regen: float
    code: int
    tag: bool
    wahrscheinlichkeit: float = 0
    uv: float = 0

    @property
    def nass(self):
        return self.regen >= REGEN_SCHWELLE or wetterart(self.code) in NASS


@dataclass
class Tag:
    datum: object
    code: int
    tmin: float
    tmax: float
    regen: float = 0
    wahrscheinlichkeit: float = 0
    uv: float = 0
    aufgang: datetime = None
    untergang: datetime = None


@dataclass
class Wetter:
    jetzt: dict
    stunden: list
    tage: list
    warnungen: list = field(default_factory=list)


def lese_open_meteo(antwort, tz):
    """Wandelt die JSON-Antwort von Open-Meteo in Stunden, Tage und aktuelle Werte."""
    h = antwort.get("hourly") or {}
    stunden = []
    for i, zeit in enumerate(h.get("time") or []):
        def wert(name, standard=0.0):
            reihe = h.get(name) or []
            return zahl(reihe[i] if i < len(reihe) else None, standard)
        stunden.append(Stunde(
            zeit=parse_zeit(zeit, tz),
            temp=wert("temperature_2m"),
            regen=wert("precipitation"),
            code=int(wert("weather_code")),
            tag=bool(wert("is_day", 1)),
            wahrscheinlichkeit=wert("precipitation_probability"),
            uv=wert("uv_index"),
        ))

    d = antwort.get("daily") or {}
    tage = []
    for i, datum in enumerate(d.get("time") or []):
        def wert(name, standard=0.0):
            reihe = d.get(name) or []
            return reihe[i] if i < len(reihe) else None
        auf, unter = wert("sunrise"), wert("sunset")
        tage.append(Tag(
            datum=datetime.fromisoformat(datum).date(),
            code=int(zahl(wert("weather_code"))),
            tmin=zahl(wert("temperature_2m_min")),
            tmax=zahl(wert("temperature_2m_max")),
            regen=zahl(wert("precipitation_sum")),
            wahrscheinlichkeit=zahl(wert("precipitation_probability_max")),
            uv=zahl(wert("uv_index_max")),
            aufgang=parse_zeit(auf, tz) if auf else None,
            untergang=parse_zeit(unter, tz) if unter else None,
        ))

    c = antwort.get("current") or {}
    jetzt = {
        "temp": zahl(c.get("temperature_2m")),
        "gefuehlt": zahl(c.get("apparent_temperature")),
        "feuchte": zahl(c.get("relative_humidity_2m")),
        "code": int(zahl(c.get("weather_code"))),
        "tag": bool(zahl(c.get("is_day"), 1)),
        "wind": zahl(c.get("wind_speed_10m")),
        "richtung": zahl(c.get("wind_direction_10m")),
        "boeen": zahl(c.get("wind_gusts_10m")),
        "regen": zahl(c.get("precipitation")),
        "bewoelkung": zahl(c.get("cloud_cover"), 50) / 100,
    }
    return Wetter(jetzt=jetzt, stunden=stunden, tage=tage)


def stunden_ab(stunden, jetzt):
    """Stunden ab der laufenden Stunde."""
    beginn = jetzt.replace(minute=0, second=0, microsecond=0)
    return [s for s in stunden if s.zeit >= beginn]


# --- Satz des Tages ---

def _zeitpunkt(dt, jetzt):
    """„15 Uhr“, nachts „3 Uhr nachts“, am nächsten Tag „morgen 7 Uhr“."""
    if dt.date() == jetzt.date():
        return f"{dt.hour}{NBSP}Uhr"
    if dt.hour < 6:
        return f"{dt.hour}{NBSP}Uhr nachts"
    return f"morgen {dt.hour}{NBSP}Uhr"


def _nass_wort(stunden):
    arten = {wetterart(s.code) for s in stunden}
    if "gewitter" in arten:
        return "Gewitter"
    if "schnee" in arten:
        return "Schnee"
    if "schauer" in arten and "regen" not in arten:
        return "Schauer"
    return "Regen"


def satz_heute(stunden, jetzt, fenster=12):
    """Ein kurzer Satz über die nächsten Stunden, als Teile [(text, hervorheben)].

    Hervorgehoben wird das, worauf es ankommt (z. B. „15 Uhr Regen“).
    """
    vorschau = stunden_ab(stunden, jetzt)[:fenster]
    if not vorschau:
        return [("Keine Vorhersage verfügbar.", False)]

    nass = [s.nass for s in vorschau]
    if nass[0]:
        # Es regnet gerade (oder in dieser Stunde) – wann wird es trocken?
        for i in range(1, len(vorschau)):
            if not nass[i] and (i + 1 >= len(nass) or not nass[i + 1]):
                wort = _nass_wort(vorschau[:i])
                return [(f"{wort} bis etwa ", False), (_zeitpunkt(vorschau[i].zeit, jetzt), True),
                        (", danach trocken.", False)]
        return [(f"{_nass_wort(vorschau)} hält an.", True)]

    if any(nass):
        beginn = nass.index(True)
        ende = next((i for i in range(beginn + 1, len(nass)) if not nass[i]), None)
        wort = _nass_wort(vorschau[beginn:ende])
        teile = [("Ab ", False), (f"{_zeitpunkt(vorschau[beginn].zeit, jetzt)} {wort}", True)]
        if ende is not None and not any(nass[ende:]):
            teile.append((f", ab {_zeitpunkt(vorschau[ende].zeit, jetzt)} trocken.", False))
        else:
            teile.append((".", False))
        return teile

    arten = [wetterart(s.code) for s in vorschau if s.tag] or [wetterart(s.code) for s in vorschau]
    if arten.count("nebel") * 2 >= len(arten):
        return [("Neblig und trocken.", False)]
    sonnig = sum(a in ("sonne", "heiter") for a in arten)
    if not any(s.tag for s in vorschau):
        return [("Trockene Nacht.", False)]
    if sonnig * 3 >= len(arten) * 2:
        return [("Sonnig und trocken.", False)]
    if sonnig:
        return [("Trocken, zeitweise sonnig.", False)]
    return [("Trocken, aber bewölkt.", False)]


def satz_morgen(tage, heute):
    """„Morgen sonnig und 3° wärmer.“ – Vergleich der Höchstwerte."""
    morgen = next((t for t in tage if t.datum > heute), None)
    jetzt_tag = next((t for t in tage if t.datum == heute), None)
    if not morgen:
        return ""
    wort = wetterwort(morgen.code)
    if not jetzt_tag:
        return f"Morgen {wort}."
    diff = grad(morgen.tmax) - grad(jetzt_tag.tmax)
    if diff >= 3:
        return f"Morgen {wort} und {diff}° wärmer."
    if diff <= -3:
        return f"Morgen {wort} und {-diff}° kühler."
    return f"Morgen {wort}, ähnlich warm."


# --- Stundenstreifen ---

def stundenstreifen(stunden, jetzt, jetzt_werte=None):
    """„Jetzt“ und danach alle 2 Stunden; Regen summiert je Feld."""
    vorschau = stunden_ab(stunden, jetzt)
    felder = []
    for i in range(STUNDEN_FELDER):
        gruppe = vorschau[i * STUNDEN_SCHRITT:(i + 1) * STUNDEN_SCHRITT]
        if not gruppe:
            break
        erste = gruppe[0]
        wichtigste = max(gruppe, key=lambda s: GEWICHT[wetterart(s.code)])
        regen = round(sum(s.regen for s in gruppe), 1)
        if i == 0 and jetzt_werte:
            temp, code, tag = jetzt_werte["temp"], jetzt_werte["code"], jetzt_werte["tag"]
        else:
            temp, code, tag = erste.temp, wichtigste.code, erste.tag
        felder.append({
            "label": "Jetzt" if i == 0 else str(erste.zeit.hour),
            "icon": icon_name(code, tag),
            "temp": grad(temp),
            "regen": regen,
            "regen_text": mm_text(regen),
            "regen_anteil": round(min(1.0, regen / REGEN_SKALA_MM), 3),
        })
    return felder


# --- Tagesliste mit Temperaturbalken ---

def temperaturfarbe(tmax, einfarbig=False):
    if einfarbig:
        return "akzent"
    if tmax < KALT_BIS:
        return "blau"
    if tmax < WARM_AB:
        return "orange"
    return "rot"


def tagesliste(tage, heute, anzahl, jetzt_temp=None, einfarbig=False):
    """Tage ab heute mit Lage des Temperaturbalkens (in % einer gemeinsamen Skala)."""
    auswahl = [t for t in tage if t.datum >= heute][:anzahl]
    if not auswahl:
        return []
    lo = min(grad(t.tmin) for t in auswahl)
    hi = max(grad(t.tmax) for t in auswahl)
    if jetzt_temp is not None:
        lo, hi = min(lo, grad(jetzt_temp)), max(hi, grad(jetzt_temp))
    spanne = max(hi - lo, 1)

    def pos(wert):
        return round((grad(wert) - lo) / spanne * 100, 1)

    zeilen = []
    for i, t in enumerate(auswahl):
        ist_heute = t.datum == heute
        zeilen.append({
            "name": "Heute" if ist_heute else WOCHENTAGE[t.datum.weekday()],
            "kurz": "Heute" if ist_heute else WOCHENTAGE_KURZ[t.datum.weekday()],
            "heute": ist_heute,
            "icon": icon_name(t.code),
            "tmin": grad(t.tmin),
            "tmax": grad(t.tmax),
            "von": pos(t.tmin),
            "bis": pos(t.tmax),
            "farbe": temperaturfarbe(grad(t.tmax), einfarbig),
            "prozent": round(t.wahrscheinlichkeit) if t.wahrscheinlichkeit >= REGEN_PROZENT_AB else None,
            "punkt": pos(jetzt_temp) if ist_heute and jetzt_temp is not None else None,
        })
    return zeilen


# --- Details unter der Heute-Ansicht ---

def parse_details(wert):
    """Bis zu drei gewählte Details; unbekannte werden ignoriert."""
    if wert is None:
        return list(STANDARD_DETAILS)
    if isinstance(wert, str):
        wert = [w.strip() for w in wert.split(",")]
    gewaehlt = []
    for w in wert:
        if w in DETAILS and w not in gewaehlt:
            gewaehlt.append(w)
    return gewaehlt[:MAX_DETAILS]


def details(gewaehlt, jetzt, heute_tag, jetzt_dt):
    """Liste von {symbol, label, wert} für die gewählten Details."""
    liste = []
    for name in gewaehlt:
        if name == "gefuehlt":
            liste.append({"symbol": "thermometer", "label": "Gefühlt", "wert": f"{grad(jetzt['gefuehlt'])}°"})
        elif name == "wind":
            text = f"{round(jetzt['wind'])} km/h"
            if round(jetzt["wind"]) > 0:
                text += f" {himmelsrichtung(jetzt['richtung'])}"
            liste.append({"symbol": "wind", "label": "Wind", "wert": text})
        elif name == "regen":
            menge = heute_tag.regen if heute_tag else 0
            liste.append({"symbol": "tropfen", "label": "Regen", "wert": mm_text(menge) or "0 mm"})
        elif name == "uv":
            uv = heute_tag.uv if heute_tag else 0
            liste.append({"symbol": "uv", "label": "UV", "wert": str(round(uv))})
        elif name == "feuchte":
            liste.append({"symbol": "feuchte", "label": "Luftfeuchte", "wert": f"{round(jetzt['feuchte'])} %"})
        elif name == "sonne" and heute_tag and heute_tag.aufgang and heute_tag.untergang:
            if jetzt_dt < heute_tag.aufgang:
                liste.append({"symbol": "aufgang", "label": "Aufgang", "wert": uhrzeit(heute_tag.aufgang)})
            else:
                liste.append({"symbol": "untergang", "label": "Untergang", "wert": uhrzeit(heute_tag.untergang)})
    return liste


# --- Warnungen des DWD (über Bright Sky) ---

WARNSTUFEN = {"minor": 1, "moderate": 2, "severe": 3, "extreme": 4}
KLEINE_WOERTER = {"MIT", "UND", "VOR", "VON", "IM", "IN", "AM", "BIS", "ODER"}


def warn_titel(text):
    """„STARKES GEWITTER mit STURMBÖEN“ → „Starkes Gewitter mit Sturmböen“."""
    woerter = []
    for wort in str(text or "").split():
        woerter.append(wort.lower() if wort.upper() in KLEINE_WOERTER and woerter else wort.capitalize())
    return " ".join(woerter)


def _tag_wort(dt, jetzt):
    if dt.date() == jetzt.date():
        return "heute"
    if dt.date() == (jetzt + timedelta(days=1)).date():
        return "morgen"
    return WOCHENTAGE_KURZ[dt.weekday()]


def warn_zeitraum(beginn, ende, jetzt):
    if beginn <= jetzt:
        if ende is None:
            return "jetzt"
        return f"bis {_tag_wort(ende, jetzt) + ' ' if ende.date() != jetzt.date() else ''}{ende.hour} Uhr"
    text = f"{_tag_wort(beginn, jetzt)} {beginn.hour}"
    if ende is None:
        return text + " Uhr"
    if ende.date() == beginn.date():
        return f"{text} – {ende.hour} Uhr"
    return f"{text} Uhr – {_tag_wort(ende, jetzt)} {ende.hour} Uhr"


def lese_warnungen(antwort, tz, jetzt, vorlauf_stunden=24):
    """Gültige oder in den nächsten 24 Stunden beginnende Warnungen, schwerste zuerst."""
    warnungen = []
    for a in (antwort or {}).get("alerts") or []:
        try:
            beginn = parse_zeit(a.get("onset") or a.get("effective"), tz)
            ende = parse_zeit(a["expires"], tz) if a.get("expires") else None
        except (TypeError, ValueError):
            continue
        if ende is not None and ende <= jetzt:
            continue
        if beginn > jetzt + timedelta(hours=vorlauf_stunden):
            continue
        stufe = WARNSTUFEN.get(str(a.get("severity", "")).lower(), 1)
        warnungen.append({
            "stufe": stufe,
            "titel": warn_titel(a.get("event_de") or a.get("headline_de") or "Wetterwarnung"),
            "zeitraum": warn_zeitraum(beginn, ende, jetzt),
            "beginn": beginn,
        })
    warnungen.sort(key=lambda w: (-w["stufe"], w["beginn"]))
    return warnungen


# --- Zusammenbau für das Template ---

def baue_ansicht(wetter, jetzt, gewaehlte_details, einfarbig=False, anzahl_tage=7):
    heute = jetzt.date()
    heute_tag = next((t for t in wetter.tage if t.datum == heute), None)
    j = wetter.jetzt
    return {
        "datum": datum_text(heute),
        "jetzt": {
            "temp": grad(j["temp"]),
            "icon": icon_name(j["code"], j["tag"]),
            "hoch": grad(heute_tag.tmax) if heute_tag else None,
            "tief": grad(heute_tag.tmin) if heute_tag else None,
            "gefuehlt": grad(j["gefuehlt"]),
        },
        "satz": satz_heute(wetter.stunden, jetzt),
        "satz_morgen": satz_morgen(wetter.tage, heute),
        "stunden": stundenstreifen(wetter.stunden, jetzt, j),
        "tage": tagesliste(wetter.tage, heute, anzahl_tage, j["temp"], einfarbig),
        "details": details(gewaehlte_details, j, heute_tag, jetzt),
        "warnung": wetter.warnungen[0] if wetter.warnungen else None,
        "weitere_warnungen": max(0, len(wetter.warnungen) - 1),
    }
