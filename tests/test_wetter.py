import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

# Die Plugins importieren relativ zu src/ (wie beim Start von InkyPi)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from plugins.wetter.wetter_daten import (  # noqa: E402
    Stunde, Tag, baue_ansicht, details, grad, himmelsrichtung, icon_name, lese_open_meteo,
    lese_warnungen, mm_text, parse_details, satz_heute, satz_morgen, stundenstreifen,
    tagesliste, temperaturfarbe, warn_titel, wetterart,
)
from utils.eink_farben import PLATZHALTER  # noqa: E402
from plugins.wetter.wetter_icons import ICONS, SYMBOLE, symbol, wetter_icon  # noqa: E402

TZ = ZoneInfo("Europe/Berlin")
JETZT = datetime(2026, 10, 11, 11, 5, tzinfo=TZ)  # Sonntag
HEUTE = JETZT.date()


# --- Beispieldaten im Format von Open-Meteo bzw. Bright Sky ---

# Code, Min, Max, Regen (mm), Regenwahrscheinlichkeit
BEISPIEL_TAGE = [
    (61, 8, 17, 4.3, 80), (0, 6, 20, 0, 0), (1, 9, 19, 0, 10), (95, 11, 22, 6, 70),
    (61, 9, 14, 8, 90), (45, 4, 11, 0.2, 20), (71, -1, 3, 2, 60), (2, 0, 5, 0, 10),
]
# Heute je Stunde: Code und Regen; sonst heiter und trocken
BEISPIEL_HEUTE = {12: (2, 0), 13: (2, 0), 14: (3, 0.1), 15: (61, 0.7), 16: (61, 0.7),
                  17: (80, 1.3), 18: (80, 1.2), 19: (3, 0.1), 20: (3, 0), 21: (0, 0)}


def beispiel_antwort(start=HEUTE, tage=BEISPIEL_TAGE, heute=BEISPIEL_HEUTE):
    hourly = {k: [] for k in ("time", "temperature_2m", "precipitation", "precipitation_probability",
                              "weather_code", "is_day", "uv_index")}
    for t in range(len(tage)):
        tag = start + timedelta(days=t)
        code_tag, tmin, tmax = tage[t][:3]
        for h in range(24):
            # Tagesgang: Tiefstwert um 5 Uhr, Höchstwert um 14 Uhr
            anteil = max(0.0, 1 - abs(h - 14) / 9) if h >= 5 else 0.0
            code, regen = heute.get(h, (1, 0)) if t == 0 else (code_tag, 0)
            hourly["time"].append(f"{tag.isoformat()}T{h:02d}:00")
            hourly["temperature_2m"].append(round(tmin + (tmax - tmin) * anteil, 1))
            hourly["precipitation"].append(regen)
            hourly["precipitation_probability"].append(80 if regen else 5)
            hourly["weather_code"].append(code)
            hourly["is_day"].append(1 if 8 <= h <= 18 else 0)
            hourly["uv_index"].append(3 if 11 <= h <= 15 else 0)
    daily = {
        "time": [(start + timedelta(days=t)).isoformat() for t in range(len(tage))],
        "weather_code": [t[0] for t in tage],
        "temperature_2m_min": [t[1] for t in tage],
        "temperature_2m_max": [t[2] for t in tage],
        "precipitation_sum": [t[3] for t in tage],
        "precipitation_probability_max": [t[4] for t in tage],
        "sunrise": [f"{(start + timedelta(days=t)).isoformat()}T07:42" for t in range(len(tage))],
        "sunset": [f"{(start + timedelta(days=t)).isoformat()}T18:51" for t in range(len(tage))],
        "uv_index_max": [3] * len(tage),
    }
    current = {"time": f"{start.isoformat()}T11:00", "temperature_2m": 14.2, "apparent_temperature": 12.4,
               "relative_humidity_2m": 72, "is_day": 1, "weather_code": 1, "wind_speed_10m": 18.3,
               "wind_direction_10m": 230, "wind_gusts_10m": 35, "precipitation": 0}
    return {"current": current, "hourly": hourly, "daily": daily}


BEISPIEL_WARNUNGEN = {"alerts": [
    {"severity": "minor", "event_de": "WINDBÖEN", "headline_de": "Amtliche WARNUNG vor WINDBÖEN",
     "onset": "2026-10-11T14:00:00+02:00", "expires": "2026-10-11T20:00:00+02:00"},
]}


def stunden(*werte, ab=JETZT.replace(minute=0)):
    """Stunden ab `ab`; jedes Element ist (code, regen)."""
    return [Stunde(zeit=ab + timedelta(hours=i), temp=10, regen=r, code=c, tag=8 <= (ab.hour + i) % 24 <= 18)
            for i, (c, r) in enumerate(werte)]


# --- Wettercodes und Icons ---

def test_wettercodes_werden_gruppiert():
    assert [wetterart(c) for c in (0, 1, 2, 3, 45, 53, 63, 66, 73, 85, 81, 95, 99)] == [
        "sonne", "heiter", "wolkig", "bedeckt", "nebel", "regen", "regen", "regen",
        "schnee", "schnee", "schauer", "gewitter", "gewitter"]


def test_nachts_mond_statt_sonne():
    assert icon_name(0, tag=False) == "mond"
    assert icon_name(1, tag=False) == "mond_wolke"
    assert icon_name(80, tag=False) == "regen"
    assert icon_name(3, tag=False) == "bedeckt"


def test_jedes_icon_ist_ein_svg_ohne_feste_grauwerte():
    for name in ICONS:
        svg = wetter_icon(name)
        assert svg.startswith("<svg") and svg.endswith("</svg>")
        # Farben nur über Variablen bzw. currentColor – sonst rastert das E-Ink-Display
        assert "#" not in svg
    for name in SYMBOLE:
        assert "#" not in symbol(name)
    assert wetter_icon("unbekannt") == wetter_icon("wolkig")


def test_hilfsfunktionen():
    assert grad(-0.4) == 0 and grad(13.6) == 14 and grad(None) == 0
    assert mm_text(0.04) == "" and mm_text(1.25) == "1,2 mm" and mm_text(12.4) == "12 mm"
    assert himmelsrichtung(230) == "SW" and himmelsrichtung(359) == "N"


# --- Satz des Tages ---

def satz_text(teile):
    return "".join(t for t, _ in teile).replace("\u00a0", " ")


def test_satz_regen_beginnt_und_endet():
    s = stunden((1, 0), (2, 0), (3, 0), (3, 0), (61, 0.7), (61, 0.9), (61, 0.3), (61, 0.4), (3, 0), (3, 0))
    teile = satz_heute(s, JETZT)
    assert satz_text(teile) == "Ab 15 Uhr Regen, ab 19 Uhr trocken."
    assert ("15\u00a0Uhr Regen", True) in teile  # Zahl und „Uhr“ bleiben zusammen


def test_satz_regen_ohne_ende_und_gewitter():
    s = stunden((1, 0), (2, 0), (95, 2), (61, 1), (61, 1))
    assert satz_text(satz_heute(s, JETZT)) == "Ab 13 Uhr Gewitter."


def test_satz_es_regnet_gerade():
    s = stunden((61, 1), (61, 0.5), (3, 0), (3, 0), (1, 0))
    assert satz_text(satz_heute(s, JETZT)) == "Regen bis etwa 13 Uhr, danach trocken."
    assert satz_text(satz_heute(stunden((71, 1), (71, 1), (71, 1)), JETZT)) == "Schnee hält an."


def test_satz_trocken():
    assert satz_text(satz_heute(stunden(*[(0, 0)] * 8), JETZT)) == "Sonnig und trocken."
    assert satz_text(satz_heute(stunden(*[(3, 0)] * 8), JETZT)) == "Trocken, aber bewölkt."
    assert satz_text(satz_heute(stunden((1, 0), (3, 0), (3, 0), (3, 0)), JETZT)) == "Trocken, zeitweise sonnig."
    assert satz_text(satz_heute(stunden(*[(45, 0)] * 6), JETZT)) == "Neblig und trocken."


def test_satz_kleine_regenmengen_zaehlen_nicht():
    assert satz_text(satz_heute(stunden((3, 0), (3, 0.1), (3, 0)), JETZT)) == "Trocken, aber bewölkt."


def test_satz_abends_nennt_nacht_und_morgen():
    abend = datetime(2026, 10, 11, 22, 10, tzinfo=TZ)
    s = stunden(*[(0, 0)] * 5 + [(61, 1)], ab=abend.replace(minute=0))
    assert satz_text(satz_heute(s, abend)) == "Ab 3 Uhr nachts Regen."
    s = stunden(*[(0, 0)] * 10 + [(61, 1)], ab=abend.replace(minute=0))
    assert satz_text(satz_heute(s, abend)) == "Ab morgen 8 Uhr Regen."


def test_satz_morgen():
    def tag(d, code, tmax):
        return Tag(datum=HEUTE + timedelta(days=d), code=code, tmin=0, tmax=tmax)
    assert satz_morgen([tag(0, 3, 17), tag(1, 0, 20)], HEUTE) == "Morgen sonnig und 3° wärmer."
    assert satz_morgen([tag(0, 3, 17), tag(1, 80, 12)], HEUTE) == "Morgen mit Schauern und 5° kühler."
    assert satz_morgen([tag(0, 3, 17), tag(1, 3, 18)], HEUTE) == "Morgen trüb, ähnlich warm."
    assert satz_morgen([tag(0, 3, 17)], HEUTE) == ""


# --- Stundenstreifen und Tagesliste ---

def test_stundenstreifen_in_zwei_stunden_schritten():
    wetter = lese_open_meteo(beispiel_antwort(), TZ)
    felder = stundenstreifen(wetter.stunden, JETZT, wetter.jetzt)
    assert [f["label"] for f in felder] == ["Jetzt", "13", "15", "17", "19", "21", "23"]
    assert felder[0]["temp"] == 14 and felder[0]["icon"] == "heiter"  # aktuelle Werte
    assert felder[2]["regen"] == 1.4 and felder[2]["regen_text"] == "1,4 mm"
    assert felder[3]["icon"] == "schauer" and felder[3]["regen_anteil"] == 0.625
    assert felder[5]["icon"] == "mond_wolke"  # nachts, 22 Uhr heiter


def test_tagesliste_mit_gemeinsamer_skala():
    wetter = lese_open_meteo(beispiel_antwort(), TZ)
    zeilen = tagesliste(wetter.tage, HEUTE, 7, jetzt_temp=14.2)
    assert [z["kurz"] for z in zeilen] == ["Heute", "Mo", "Di", "Mi", "Do", "Fr", "Sa"]
    assert zeilen[0]["name"] == "Heute" and zeilen[1]["name"] == "Montag"
    # Skala von -1° (Sa) bis 22° (Mi)
    assert zeilen[6]["von"] == 0 and zeilen[3]["bis"] == 100
    assert zeilen[0]["punkt"] == round(15 / 23 * 100, 1) and zeilen[1]["punkt"] is None
    assert [z["prozent"] for z in zeilen] == [80, None, None, 70, 90, 20, 60]
    assert [z["farbe"] for z in zeilen][:4] == ["orange", "orange", "orange", "rot"]
    assert zeilen[6]["farbe"] == "blau"
    assert all(z["farbe"] == "akzent" for z in tagesliste(wetter.tage, HEUTE, 7, einfarbig=True))


def test_temperaturfarbe_grenzen():
    assert [temperaturfarbe(t) for t in (7, 8, 21, 22)] == ["blau", "orange", "orange", "rot"]


# --- Details ---

def test_details_auswahl():
    assert parse_details(None) == ["wind", "regen", "uv"]
    assert parse_details("") == []
    assert parse_details(["sonne", "quatsch", "sonne", "uv", "wind", "regen"]) == ["sonne", "uv", "wind"]
    assert parse_details("gefuehlt,feuchte") == ["gefuehlt", "feuchte"]


def test_details_werte():
    wetter = lese_open_meteo(beispiel_antwort(), TZ)
    heute = wetter.tage[0]
    liste = details(["gefuehlt", "wind", "regen", "uv", "feuchte", "sonne"], wetter.jetzt, heute, JETZT)
    assert [(d["label"], d["wert"]) for d in liste] == [
        ("Gefühlt", "12°"), ("Wind", "18 km/h SW"), ("Regen", "4,3 mm"), ("UV", "3"),
        ("Luftfeuchte", "72 %"), ("Untergang", "18:51")]
    frueh = JETZT.replace(hour=6)
    assert details(["sonne"], wetter.jetzt, heute, frueh)[0]["wert"] == "7:42"


# --- Warnungen ---

def test_warn_titel():
    assert warn_titel("STARKES GEWITTER mit STURMBÖEN") == "Starkes Gewitter mit Sturmböen"
    assert warn_titel("FROST") == "Frost"


def test_warnungen_werden_gefiltert_und_sortiert():
    antwort = {"alerts": [
        {"severity": "minor", "event_de": "FROST", "onset": "2026-10-11T22:00:00+02:00",
         "expires": "2026-10-12T09:00:00+02:00"},
        {"severity": "moderate", "event_de": "STURMBÖEN", "onset": "2026-10-11T09:00:00+02:00",
         "expires": "2026-10-11T20:00:00+02:00"},
        {"severity": "severe", "event_de": "ORKANBÖEN", "onset": "2026-10-10T09:00:00+02:00",
         "expires": "2026-10-10T20:00:00+02:00"},  # abgelaufen
        {"severity": "extreme", "event_de": "HITZE", "onset": "2026-10-14T09:00:00+02:00",
         "expires": "2026-10-14T20:00:00+02:00"},  # zu weit in der Zukunft
    ]}
    warnungen = lese_warnungen(antwort, TZ, JETZT)
    assert [(w["titel"], w["stufe"], w["zeitraum"]) for w in warnungen] == [
        ("Sturmböen", 2, "bis 20 Uhr"),
        ("Frost", 1, "heute 22 Uhr – morgen 9 Uhr"),
    ]
    assert lese_warnungen(BEISPIEL_WARNUNGEN, TZ, JETZT)[0]["zeitraum"] == "heute 14 – 20 Uhr"
    assert lese_warnungen({}, TZ, JETZT) == []


# --- Zusammenbau ---

def test_baue_ansicht():
    wetter = lese_open_meteo(beispiel_antwort(), TZ)
    wetter.warnungen = lese_warnungen(BEISPIEL_WARNUNGEN, TZ, JETZT)
    daten = baue_ansicht(wetter, JETZT, ["wind", "regen", "uv"])
    assert daten["datum"] == "Sonntag, 11. Oktober"
    assert daten["jetzt"] == {"temp": 14, "icon": "heiter", "hoch": 17, "tief": 8, "gefuehlt": 12}
    assert satz_text(daten["satz"]) == "Ab 15 Uhr Regen, ab 19 Uhr trocken."
    assert daten["satz_morgen"] == "Morgen sonnig und 3° wärmer."
    assert len(daten["stunden"]) == 7 and len(daten["tage"]) == 7
    assert daten["warnung"]["titel"] == "Windböen" and daten["weitere_warnungen"] == 0


def test_lese_open_meteo_mit_luecken():
    antwort = beispiel_antwort(tage=BEISPIEL_TAGE[:2])
    antwort["hourly"]["precipitation_probability"] = [None] * len(antwort["hourly"]["time"])
    del antwort["daily"]["uv_index_max"]
    wetter = lese_open_meteo(antwort, TZ)
    assert wetter.stunden[0].wahrscheinlichkeit == 0
    assert wetter.tage[0].uv == 0 and wetter.tage[0].datum == date(2026, 10, 11)
    assert wetter.stunden[0].zeit.tzinfo is TZ


# --- Plugin (braucht die Laufzeit-Abhängigkeiten) ---

class GeraetDummy:
    def __init__(self, **werte):
        self.werte = {"timezone": "Europe/Berlin", "display_type": "epd7in3f", **werte}

    def get_resolution(self):
        return (800, 480)

    def get_config(self, schluessel, default=None):
        return self.werte.get(schluessel, default)


def plugin_mit_daten(monkeypatch, warnungen=BEISPIEL_WARNUNGEN):
    for modul in ("requests", "PIL", "jinja2", "numpy"):
        pytest.importorskip(modul)
    from plugins.wetter.wetter import Wetter

    monkeypatch.setattr(Wetter, "vorhersage", staticmethod(lambda lat, lon, tz: beispiel_antwort()))
    if isinstance(warnungen, Exception):
        def kaputt(lat, lon, tz):
            raise warnungen
        monkeypatch.setattr(Wetter, "warnungen", staticmethod(kaputt))
    else:
        monkeypatch.setattr(Wetter, "warnungen", staticmethod(lambda lat, lon, tz: warnungen))
    monkeypatch.setattr(Wetter, "jetzt", staticmethod(lambda tz: JETZT))
    plugin = Wetter({"id": "wetter"})
    erfasst = {}

    def render_image(dimensions, html, css, params):
        erfasst.update(params)
        from PIL import Image
        # Kleines Bild mit dem Platzhalter des Gelbs – muss beim Thema „E-Ink“ ersetzt werden
        return Image.new("RGB", (4, 2), params["farben"]["gelb"])
    plugin.render_image = render_image
    return plugin, erfasst


def test_plugin_uebergibt_ansicht_und_eink_farben(monkeypatch):
    plugin, params = plugin_mit_daten(monkeypatch)
    einstellungen = {"latitude": "47.99", "longitude": "7.85", "ortName": "Freiburg", "ansicht": "beides",
                     "temperaturfarbe": "einfarbig", "iconstil": "linien", "akzentfarbe": "#e0393e"}
    bild = plugin.generate_image(einstellungen, GeraetDummy())
    assert params["ort"] == "Freiburg" and params["ansicht"] == "beides" and params["icons"] == "linien"
    assert len(params["daten"]["tage"]) == 6
    assert params["daten"]["tage"][0]["farbe"] == "akzent"
    # Waveshare: reine Farben, Akzent auf die nächste Displayfarbe gesetzt
    assert params["farben"]["rot"] == "#ff0000" and params["farben"]["bg"] == "#ffffff"
    assert params["akzent"] == "#ff0000"
    # Gelb ist die Mischung Gelb ¾ + Orange: im Template Platzhalter, im Bild das Muster
    assert params["farben"]["gelb"] == PLATZHALTER["gelb_orange_75"]
    assert params["farben"]["orange"] == PLATZHALTER["rot_orange_50"]
    assert sorted(farbe for _, farbe in bild.getcolors()) == [(255, 128, 0), (255, 255, 0)]
    assert params["daten"]["warnung"]["titel"] == "Windböen"


def test_plugin_ohne_warnungsdienst_und_ohne_warnband(monkeypatch):
    plugin, params = plugin_mit_daten(monkeypatch, warnungen=RuntimeError("down"))
    plugin.generate_image({"latitude": "47.99", "longitude": "7.85"}, GeraetDummy())
    assert params["daten"]["warnung"] is None and params["ansicht"] == "heute"

    plugin, params = plugin_mit_daten(monkeypatch)
    plugin.generate_image({"latitude": "47.99", "longitude": "7.85", "warnungen": "false"}, GeraetDummy())
    assert params["daten"]["warnung"] is None


def test_plugin_braucht_ort(monkeypatch):
    plugin, _ = plugin_mit_daten(monkeypatch)
    with pytest.raises(RuntimeError, match="Ort"):
        plugin.generate_image({}, GeraetDummy())
