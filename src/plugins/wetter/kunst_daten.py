"""Daten für die künstlerischen Wetter-Ansichten „Fenster“ und „Poesie“.

„Fenster“ ist eine kleine Landschaft, die das echte Wetter nachspielt: Sonne
auf ihrem Tagesbogen, Mond in der richtigen Phase, Wolken nach Bewölkung,
Regen schräg im Wind und ein Baum, der sich durch das Jahr verändert.

„Poesie“ ist ein typografisches Plakat: ein großes Wort und drei kurze Zeilen,
die nach festen Regeln aus der Vorhersage entstehen – ohne KI, verlässlich.

Bewusst ohne Fremdbibliotheken, damit alles in der GitHub Action testbar ist.
"""

from datetime import datetime, timedelta, timezone

from plugins.wetter.wetter_daten import NASS, grad, stunden_ab, wetterart

# --- Mond ---

SYNODISCHER_MONAT = 29.530588853
# Ein bekannter Neumond als Bezugspunkt (6. Januar 2000, 18:14 UTC)
NEUMOND = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)


def mondphase(zeitpunkt):
    """0 = Neumond, 0,25 = zunehmender Halbmond, 0,5 = Vollmond, 0,75 = abnehmend."""
    tage = (zeitpunkt.astimezone(timezone.utc) - NEUMOND).total_seconds() / 86400
    return round((tage % SYNODISCHER_MONAT) / SYNODISCHER_MONAT, 3) % 1.0


# --- Jahreszeit des Baums ---

BAUM_NACH_MONAT = {
    1: "kahl", 2: "kahl", 3: "knospen", 4: "bluete", 5: "bluete", 6: "gruen",
    7: "gruen", 8: "aepfel", 9: "herbstbeginn", 10: "herbst", 11: "spaetherbst", 12: "kahl",
}


def baum(datum):
    return BAUM_NACH_MONAT[datum.month]


# --- Szene „Fenster“ ---

def sonnenstand(jetzt, heute_tag):
    """Lage der Sonne auf ihrem Tagesbogen: 0 = Aufgang, 1 = Untergang, None = Nacht."""
    if not heute_tag or not heute_tag.aufgang or not heute_tag.untergang:
        return None
    if not heute_tag.aufgang <= jetzt <= heute_tag.untergang:
        return None
    dauer = (heute_tag.untergang - heute_tag.aufgang).total_seconds()
    return round((jetzt - heute_tag.aufgang).total_seconds() / dauer, 3)


def _heute(wetter, jetzt):
    return next((t for t in wetter.tage if t.datum == jetzt.date()), None)


def ist_nacht(wetter, jetzt):
    """Nacht zwischen Sonnenunter- und -aufgang; ohne diese Zeiten nach Open-Meteo."""
    heute = _heute(wetter, jetzt)
    if heute and heute.aufgang and heute.untergang:
        return sonnenstand(jetzt, heute) is None
    return not wetter.jetzt["tag"]


def szene_fenster(wetter, jetzt):
    """Alles, was die Landschaft braucht – gezeichnet wird im Template."""
    j = wetter.jetzt
    heute = _heute(wetter, jetzt)
    bald = stunden_ab(wetter.stunden, jetzt)[:2]
    art = wetterart(j["code"])
    regen = max([j["regen"]] + [s.regen for s in bald[:1]])
    if art in NASS and regen < 0.3:
        regen = 0.5  # Nieselregen soll trotzdem sichtbar sein
    stand = sonnenstand(jetzt, heute)
    bewoelkung = max(j["bewoelkung"], {"bedeckt": 0.9, "regen": 0.9, "schnee": 0.9, "gewitter": 0.85,
                                       "nebel": 0.8, "schauer": 0.6}.get(art, 0))
    return {
        "nacht": stand is None,
        "sonnenstand": stand or 0,
        "bewoelkung": round(min(1.0, bewoelkung), 2),
        "regen": round(regen, 1) if art in NASS and art != "schnee" else 0,
        "schnee": art == "schnee",
        "gewitter": art == "gewitter",
        "nebel": art == "nebel",
        "wind": round(j["wind"]),
        "windrichtung": round(j["richtung"]),
        "mond": mondphase(jetzt),
        "baum": baum(jetzt.date()),
        "temp": grad(j["temp"]),
    }


# --- Poesie ---

ZAHLWOERTER = ["zwölf", "eins", "zwei", "drei", "vier", "fünf", "sechs", "sieben", "acht", "neun", "zehn", "elf"]

ZUSTAND = {
    "sonne": "Sonne", "heiter": "Freundlich", "wolkig": "Wolken", "bedeckt": "Grau", "nebel": "Nebel",
    "regen": "Regen", "schauer": "Schauer", "schnee": "Schnee", "gewitter": "Gewitter",
}
ZUSTAND_NACHT = {"sonne": "Klar", "heiter": "Meist klar"}

NASS_MIT_ARTIKEL = {"Regen": "der Regen", "Schnee": "der Schnee", "Schauer": "die Schauer", "Gewitter": "das Gewitter"}
# Wie es endet: „ab vier hört der Schnee auf“
NASS_ENDE = {
    "Regen": "wird es trocken", "Schnee": "hört der Schnee auf", "Schauer": "hören die Schauer auf",
    "Gewitter": "zieht das Gewitter ab",
}


def uhr_wort(stunde):
    """„drei“ für 3 oder 15 Uhr, „Mitternacht“ für 0 Uhr – so klingt es nach Sprache, nicht nach Fahrplan."""
    if stunde == 0:
        return "Mitternacht"
    return ZAHLWOERTER[stunde % 12]


def tageszeit(stunde):
    if stunde < 5:
        return "in der Nacht"
    if stunde < 11:
        return "am Morgen"
    if stunde < 14:
        return "am Mittag"
    if stunde < 18:
        return "am Nachmittag"
    if stunde < 22:
        return "am Abend"
    return "in der Nacht"


def _auswahl(liste, jetzt):
    """Abwechslung von Tag zu Tag, aber am selben Tag immer dasselbe Wort."""
    return liste[jetzt.toordinal() % len(liste)]


def _nass_wort(arten):
    if "gewitter" in arten:
        return "Gewitter"
    if "schnee" in arten:
        return "Schnee"
    if "schauer" in arten and "regen" not in arten:
        return "Schauer"
    return "Regen"


def poesie_lage(wetter, jetzt):
    """Welches Farbplakat: sonne, regen, nacht, gewitter, schnee oder wolken."""
    j = wetter.jetzt
    vorschau = stunden_ab(wetter.stunden, jetzt)[:12]
    art = wetterart(j["code"])
    if art == "gewitter" or any(wetterart(s.code) == "gewitter" for s in vorschau[:6]):
        return "gewitter"
    if art == "schnee" or any(wetterart(s.code) == "schnee" for s in vorschau[:3]):
        return "schnee"
    if art in NASS or j["regen"] >= 0.2:
        return "regen"
    if ist_nacht(wetter, jetzt):
        return "nacht"
    if any(s.nass for s in vorschau[:8]):
        return "regen"
    if art in ("bedeckt", "nebel") or j["bewoelkung"] > 0.7:
        return "wolken"
    return "sonne"


def poesie_wort(lage, wetter, jetzt):
    heute = _heute(wetter, jetzt)
    hoch = grad(heute.tmax) if heute else grad(wetter.jetzt["temp"])
    tief = grad(heute.tmin) if heute else grad(wetter.jetzt["temp"])
    art = wetterart(wetter.jetzt["code"])
    monat = jetzt.month
    if lage == "gewitter":
        return "Gewitter!"
    if lage == "schnee":
        return _auswahl(["Schnee.", "Flockenwirbel.", "Winterweiß."], jetzt)
    if lage == "regen":
        vorschau = stunden_ab(wetter.stunden, jetzt)[:12]
        if vorschau and all(s.nass for s in vorschau):
            return "Landregen."
        if art == "schauer":
            return "Schauer."
        return _auswahl(["Regen.", "Regenwetter.", "Regen."], jetzt)
    if lage == "nacht":
        if wetter.jetzt["bewoelkung"] < 0.4:
            return "Frostnacht." if tief <= 0 else "Sternklar."
        return _auswahl(["Gute Nacht.", "Nachtruhe."], jetzt)
    if lage == "wolken":
        if art == "nebel":
            return "Nebel."
        return _auswahl(["Grau in grau.", "Bedeckt.", "Wolkig."], jetzt)
    # Sonne
    if hoch >= 30:
        return "Hitze!"
    if tief <= 0:
        return "Klirrend klar."
    if monat == 9:
        return "Altweibersommer."
    if monat == 10:
        return "Goldener Oktober."
    if monat in (3, 4, 5):
        return _auswahl(["Frühling.", "Frühlingssonne."], jetzt)
    if hoch >= 25:
        return _auswahl(["Sommer.", "Sonnenschein."], jetzt)
    return _auswahl(["Sonnig.", "Strahlend.", "Blauer Himmel."], jetzt)


def poesie_zeilen(wetter, jetzt):
    """Drei Zeilen: wie es jetzt ist, was heute passiert, wie es weitergeht."""
    j = wetter.jetzt
    art = wetterart(j["code"])
    zustand = (ZUSTAND_NACHT.get(art) if ist_nacht(wetter, jetzt) else None) or ZUSTAND[art]
    erste = f"{zustand} {tageszeit(jetzt.hour)}."

    vorschau = stunden_ab(wetter.stunden, jetzt)[:12]
    nass = [s.nass for s in vorschau]
    if nass and nass[0]:
        ende = next((i for i in range(1, len(nass)) if not nass[i] and (i + 1 >= len(nass) or not nass[i + 1])), None)
        wort = _nass_wort({wetterart(s.code) for s in vorschau[:ende or len(vorschau)]})
        if ende is None:
            zweite = f"{NASS_MIT_ARTIKEL[wort]} bleibt,"
        else:
            zweite = f"ab {uhr_wort(vorschau[ende].zeit.hour)} {NASS_ENDE[wort]},"
    elif any(nass):
        beginn = nass.index(True)
        wort = _nass_wort({wetterart(s.code) for s in vorschau[beginn:beginn + 3]})
        zweite = f"ab {uhr_wort(vorschau[beginn].zeit.hour)} {NASS_MIT_ARTIKEL[wort]},"
    else:
        arten = [wetterart(s.code) for s in vorschau if s.tag] or [art]
        if arten.count("nebel") * 2 >= len(arten):
            zweite = "die Sonne hat es schwer,"
        elif ist_nacht(wetter, jetzt) and j["bewoelkung"] < 0.4:
            zweite = "die Sterne bleiben bis zum Morgen,"
        elif sum(a in ("sonne", "heiter") for a in arten) * 3 >= len(arten) * 2:
            zweite = "klarer Himmel bis zum Abend," if jetzt.hour < 17 else "klarer Himmel bis zum Morgen,"
        else:
            zweite = "kein Regen in Sicht,"
    zweite = zweite[0].upper() + zweite[1:]

    heute = _heute(wetter, jetzt)
    morgen = next((t for t in wetter.tage if t.datum == jetzt.date() + timedelta(days=1)), None)
    if heute and grad(heute.tmin) <= 0 and jetzt.hour < 20:
        dritte = "nachts wird es frostig."
    elif heute and morgen and grad(morgen.tmax) - grad(heute.tmax) >= 3:
        dritte = "morgen wird es wärmer."
    elif heute and morgen and grad(morgen.tmax) - grad(heute.tmax) <= -3:
        dritte = "morgen wird es kühler."
    elif j["wind"] >= 40:
        dritte = "der Wind pfeift ums Haus."
    elif morgen and wetterart(morgen.code) in ("sonne", "heiter"):
        dritte = "morgen lacht die Sonne."
    elif morgen and wetterart(morgen.code) in NASS:
        dritte = "morgen bleibt es nass."
    else:
        dritte = "abends wird es still."
    return [erste, zweite, dritte]


def poesie(wetter, jetzt):
    lage = poesie_lage(wetter, jetzt)
    heute = _heute(wetter, jetzt)
    wort = poesie_wort(lage, wetter, jetzt)
    return {
        "lage": lage,
        "wort": wort,
        # Lange Wörter kleiner, damit sie nicht ins Motiv laufen
        "groesse": "gross" if len(wort) <= 9 else "mittel" if len(wort) <= 12 else "klein",
        "zeilen": poesie_zeilen(wetter, jetzt),
        "temp": grad(wetter.jetzt["temp"]),
        "tief": grad(heute.tmin) if heute else None,
        "hoch": grad(heute.tmax) if heute else None,
    }
