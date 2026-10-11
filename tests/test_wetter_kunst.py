import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

# Die Plugins importieren relativ zu src/ (wie beim Start von InkyPi)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plugins.wetter.kunst_daten import (  # noqa: E402
    baum, ist_nacht, mondphase, poesie, poesie_lage, poesie_wort, poesie_zeilen, sonnenstand, szene_fenster,
    tageszeit, uhr_wort,
)
from plugins.wetter.wetter_daten import lese_open_meteo  # noqa: E402
from tests.test_wetter import BEISPIEL_TAGE, JETZT, TZ, GeraetDummy, beispiel_antwort  # noqa: E402

BERLIN = ZoneInfo("Europe/Berlin")


def wetter_mit(current=None, start=JETZT.date(), **kw):
    antwort = beispiel_antwort(start=start, **kw)
    antwort["current"].update(current or {})
    return lese_open_meteo(antwort, TZ)


def um(tag, stunde, minute=0):
    return datetime(tag.year, tag.month, tag.day, stunde, minute, tzinfo=TZ)


# --- Mond, Sonne, Jahreszeit ---

def test_mondphase():
    # Neumond am 10./11. Oktober 2026, Vollmond am 26. Oktober (abgeglichen mit astral)
    neumond = mondphase(datetime(2026, 10, 11, 0, tzinfo=BERLIN))
    assert neumond < 0.03 or neumond > 0.97
    assert 0.47 < mondphase(datetime(2026, 10, 26, 6, tzinfo=BERLIN)) < 0.53
    assert 0.2 < mondphase(datetime(2026, 10, 18, 12, tzinfo=BERLIN)) < 0.3  # zunehmender Halbmond
    assert 0 <= mondphase(datetime(2031, 1, 1, tzinfo=BERLIN)) < 1


def test_baum_im_jahreslauf():
    zustaende = [baum(date(2026, monat, 15)) for monat in range(1, 13)]
    assert zustaende == ["kahl", "kahl", "knospen", "bluete", "bluete", "gruen", "gruen", "aepfel",
                         "herbstbeginn", "herbst", "spaetherbst", "kahl"]


def test_sonnenstand_und_nacht():
    w = wetter_mit()
    heute = w.tage[0]  # Aufgang 7:42, Untergang 18:51
    assert sonnenstand(um(JETZT.date(), 7, 42), heute) == 0
    assert sonnenstand(um(JETZT.date(), 18, 51), heute) == 1
    assert 0.45 < sonnenstand(um(JETZT.date(), 13, 15), heute) < 0.55
    assert sonnenstand(um(JETZT.date(), 22), heute) is None
    assert ist_nacht(w, um(JETZT.date(), 22)) and not ist_nacht(w, JETZT)


# --- Szene „Fenster“ ---

def test_szene_fenster():
    szene = szene_fenster(wetter_mit({"cloud_cover": 30}), JETZT)
    assert szene["nacht"] is False and 0 < szene["sonnenstand"] < 1
    assert szene["baum"] == "herbst" and szene["temp"] == 14
    assert szene["bewoelkung"] == 0.3 and szene["regen"] == 0 and not szene["schnee"]
    assert szene["wind"] == 18 and szene["windrichtung"] == 230

    nacht = szene_fenster(wetter_mit({"is_day": 0}), um(JETZT.date(), 22))
    assert nacht["nacht"] and nacht["sonnenstand"] == 0

    regen = szene_fenster(wetter_mit({"weather_code": 63, "precipitation": 1.5, "cloud_cover": 40}), JETZT)
    assert regen["regen"] == 1.5 and regen["bewoelkung"] == 0.9  # Regen heißt: Himmel zu

    niesel = szene_fenster(wetter_mit({"weather_code": 51, "precipitation": 0.1}), JETZT)
    assert niesel["regen"] == 0.5  # auch Niesel ist sichtbar

    schnee = szene_fenster(wetter_mit({"weather_code": 73, "precipitation": 1}), JETZT)
    assert schnee["schnee"] and schnee["regen"] == 0


# --- Poesie ---

def test_uhr_wort_und_tageszeit():
    assert [uhr_wort(h) for h in (0, 1, 3, 12, 15, 19, 23)] == [
        "Mitternacht", "eins", "drei", "zwölf", "drei", "sieben", "elf"]
    assert [tageszeit(h) for h in (3, 8, 12, 15, 20, 23)] == [
        "in der Nacht", "am Morgen", "am Mittag", "am Nachmittag", "am Abend", "in der Nacht"]


def test_poesie_regen_am_nachmittag():
    w = wetter_mit()  # heiter, ab 15 Uhr Regen bis 19 Uhr, morgen sonnig und wärmer
    gedicht = poesie(w, JETZT)
    assert gedicht["lage"] == "regen"
    assert gedicht["zeilen"] == ["Freundlich am Mittag.", "Ab drei der Regen,", "morgen wird es wärmer."]
    assert gedicht["temp"] == 14 and (gedicht["tief"], gedicht["hoch"]) == (8, 17)
    assert gedicht["wort"] in ("Regen.", "Regenwetter.")
    assert gedicht["groesse"] in ("gross", "mittel")


def test_poesie_es_regnet_und_hoert_auf():
    w = wetter_mit({"weather_code": 63, "precipitation": 1.2},
                   heute={h: (63, 1.0) for h in range(10, 14)})
    assert poesie_zeilen(w, JETZT)[1] == "Ab zwei wird es trocken,"
    schnee = wetter_mit({"weather_code": 73, "precipitation": 1.0},
                        heute={h: (73, 1.0) for h in range(10, 16)})
    assert poesie_zeilen(schnee, JETZT)[1] == "Ab vier hört der Schnee auf,"
    assert poesie_lage(schnee, JETZT) == "schnee"


def test_poesie_sternklare_frostnacht():
    w = wetter_mit({"is_day": 0, "weather_code": 0, "cloud_cover": 5},
                   tage=[(0, -2, 9, 0, 0), (0, -1, 10, 0, 0)] + BEISPIEL_TAGE[2:], heute={})
    abend = um(JETZT.date(), 21, 30)
    gedicht = poesie(w, abend)
    assert gedicht["lage"] == "nacht" and gedicht["wort"] == "Frostnacht."
    assert gedicht["zeilen"] == ["Klar am Abend.", "Die Sterne bleiben bis zum Morgen,", "morgen lacht die Sonne."]


def test_poesie_worte_nach_jahreszeit():
    def sonnig(tag, tmin=8, tmax=18):
        return wetter_mit({"weather_code": 0, "cloud_cover": 0}, start=tag,
                          tage=[(0, tmin, tmax, 0, 0), (0, tmin, tmax, 0, 0)] + BEISPIEL_TAGE[2:], heute={})
    assert poesie_wort("sonne", sonnig(date(2026, 10, 11)), um(date(2026, 10, 11), 12)) == "Goldener Oktober."
    assert poesie_wort("sonne", sonnig(date(2026, 9, 20)), um(date(2026, 9, 20), 12)) == "Altweibersommer."
    assert poesie_wort("sonne", sonnig(date(2027, 7, 1), 18, 32), um(date(2027, 7, 1), 12)) == "Hitze!"
    assert poesie_wort("sonne", sonnig(date(2027, 1, 10), -6, 1), um(date(2027, 1, 10), 12)) == "Klirrend klar."
    assert poesie_wort("sonne", sonnig(date(2027, 4, 10)), um(date(2027, 4, 10), 12)) in ("Frühling.", "Frühlingssonne.")


def test_poesie_lagen():
    assert poesie_lage(wetter_mit({"weather_code": 95}), JETZT) == "gewitter"
    assert poesie_lage(wetter_mit({"weather_code": 3, "cloud_cover": 100}, heute={}), JETZT) == "wolken"
    assert poesie_lage(wetter_mit({"weather_code": 0, "cloud_cover": 0}, heute={}), JETZT) == "sonne"
    nebel = wetter_mit({"weather_code": 45}, heute={h: (45, 0) for h in range(24)})
    assert poesie_lage(nebel, JETZT) == "wolken" and poesie_wort("wolken", nebel, JETZT) == "Nebel."


def test_poesie_ist_am_selben_tag_stabil():
    w = wetter_mit({"weather_code": 3, "cloud_cover": 100}, heute={})
    assert poesie(w, JETZT) == poesie(w, JETZT + timedelta(minutes=30))


# --- Plugin (braucht die Laufzeit-Abhängigkeiten) ---

@pytest.mark.parametrize("ansicht", ["fenster", "poesie"])
def test_plugin_kunst_ansichten(monkeypatch, ansicht):
    for modul in ("requests", "PIL", "jinja2", "numpy"):
        pytest.importorskip(modul)
    from PIL import Image
    from plugins.wetter.wetter import Wetter
    from utils.eink_farben import PLATZHALTER

    monkeypatch.setattr(Wetter, "vorhersage", staticmethod(lambda lat, lon, tz: beispiel_antwort()))
    monkeypatch.setattr(Wetter, "warnungen", staticmethod(lambda lat, lon, tz: {"alerts": []}))
    monkeypatch.setattr(Wetter, "jetzt", staticmethod(lambda tz: JETZT))
    plugin = Wetter({"id": "wetter"})
    erfasst = {}

    def render_image(dimensions, html, css, params):
        erfasst.update(params, html=html, css=css)
        return Image.new("RGB", (4, 2), params["farben"]["gelb"])
    plugin.render_image = render_image

    bild = plugin.generate_image({"latitude": "47.99", "longitude": "7.85", "ortName": "Freiburg",
                                  "ansicht": ansicht}, GeraetDummy())
    assert erfasst["html"] == f"wetter_{ansicht}.html" and erfasst["css"] == "wetter_kunst.css"
    assert erfasst["datum"] == "Sonntag, 11. Oktober" and erfasst["warnung"] is None
    assert ("szene" if ansicht == "fenster" else "gedicht") in erfasst
    # Farbrollen des Farbtests, Mischfarben im Bild durch Muster ersetzt
    assert erfasst["farben"]["gelb"] == PLATZHALTER["gelb_orange_75"]
    assert sorted(farbe for _, farbe in bild.getcolors()) == [(255, 128, 0), (255, 255, 0)]


def test_gefuehlte_temperatur_waehlbar():
    w = wetter_mit()  # gemessen 14,2°, gefühlt 12,4°
    assert szene_fenster(w, JETZT)["temp"] == 14 and not szene_fenster(w, JETZT)["gefuehlt"]
    szene = szene_fenster(w, JETZT, gefuehlt=True)
    assert szene["temp"] == 12 and szene["gefuehlt"]
    gedicht = poesie(w, JETZT, gefuehlt=True)
    assert gedicht["temp"] == 12 and gedicht["gefuehlt"]
    assert (gedicht["tief"], gedicht["hoch"]) == (8, 17)  # Spanne bleibt gemessen


@pytest.mark.parametrize("wahl, erwartet", [(None, 14), ("gemessen", 14), ("gefuehlt", 12)])
def test_plugin_uebernimmt_temperaturwahl(monkeypatch, wahl, erwartet):
    for modul in ("requests", "PIL", "jinja2", "numpy"):
        pytest.importorskip(modul)
    from PIL import Image
    from plugins.wetter.wetter import Wetter

    monkeypatch.setattr(Wetter, "vorhersage", staticmethod(lambda lat, lon, tz: beispiel_antwort()))
    monkeypatch.setattr(Wetter, "warnungen", staticmethod(lambda lat, lon, tz: {"alerts": []}))
    monkeypatch.setattr(Wetter, "jetzt", staticmethod(lambda tz: JETZT))
    plugin = Wetter({"id": "wetter"})
    erfasst = {}

    def render_image(dimensions, html, css, params):
        erfasst.update(params)
        return Image.new("RGB", (2, 2), "#ffffff")
    plugin.render_image = render_image

    einstellungen = {"latitude": "47.99", "longitude": "7.85", "ansicht": "fenster"}
    if wahl:
        einstellungen["temperatur"] = wahl
    plugin.generate_image(einstellungen, GeraetDummy())
    assert erfasst["szene"]["temp"] == erwartet
    plugin.generate_image({**einstellungen, "ansicht": "poesie"}, GeraetDummy())
    assert erfasst["gedicht"]["temp"] == erwartet
