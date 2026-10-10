import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

# Die Plugins importieren relativ zu src/ (wie beim Start von InkyPi)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from plugins.icloud_kalender.kalender_daten import (  # noqa: E402
    Termin, baue_monat, baue_tag, baue_woche, kontrastfarbe, monatsraster,
    normalisiere_url, parse_stunde, spalten_verteilen, stundenbereich,
    termin_tint, termine_am_tag, wochen_titel, wochenanfang, zeitraum,
)

TZ = ZoneInfo("Europe/Berlin")


def zeit(tag, stunde, minute=0):
    return datetime(tag.year, tag.month, tag.day, stunde, minute, tzinfo=TZ)


def termin(titel, start, ende, ganztag=False, farbe="#2f6fde"):
    return Termin(titel=titel, start=start, ende=ende, ganztag=ganztag, farbe=farbe)


def ganztags(titel, von, bis_exklusiv):
    return termin(titel, zeit(von, 0), zeit(bis_exklusiv, 0), ganztag=True)


MI = date(2026, 10, 14)  # Mittwoch


def test_webcal_link_wird_zu_https():
    assert normalisiere_url(" webcal://p1-caldav.icloud.com/published/2/abc ") == \
        "https://p1-caldav.icloud.com/published/2/abc"
    assert normalisiere_url("WEBCAL://x.de/a.ics") == "https://x.de/a.ics"
    assert normalisiere_url("https://x.de/a.ics") == "https://x.de/a.ics"
    assert normalisiere_url(None) == ""


def test_parse_stunde_begrenzt_und_faellt_zurueck():
    assert parse_stunde("8", 7) == 8
    assert parse_stunde("", 7) == 7
    assert parse_stunde("abc", 21) == 21
    assert parse_stunde("30", 7) == 24
    assert parse_stunde("-3", 7) == 0


def test_wochenanfang_montag_und_sonntag():
    assert wochenanfang(MI, 0) == date(2026, 10, 12)
    assert wochenanfang(MI, 6) == date(2026, 10, 11)
    assert wochenanfang(date(2026, 10, 11), 0) == date(2026, 10, 5)  # Sonntag gehört zur Vorwoche


def test_monatsraster_deckt_ganzen_monat_in_vollen_wochen_ab():
    wochen = monatsraster(2026, 10, 0)
    assert wochen[0][0] == date(2026, 9, 28)
    assert wochen[-1][-1] == date(2026, 11, 1)
    assert all(len(w) == 7 for w in wochen)
    # Februar 2027 beginnt an einem Montag und hat genau vier Wochen
    assert len(monatsraster(2027, 2, 0)) == 4


def test_zeitraum_je_ansicht():
    assert zeitraum("tag", MI) == (MI, MI + timedelta(days=7))
    assert zeitraum("woche", MI, 0) == (date(2026, 10, 12), date(2026, 10, 19))
    assert zeitraum("monat", MI, 0) == (date(2026, 9, 28), date(2026, 11, 2))
    with pytest.raises(ValueError):
        zeitraum("jahr", MI)


def test_termine_am_tag_trennt_ganztaegig_und_zeitlich():
    termine = [
        termin("Meeting", zeit(MI, 10), zeit(MI, 11, 30)),
        ganztags("Geburtstag", MI, MI + timedelta(days=1)),
        termin("Gestern", zeit(MI - timedelta(days=1), 10), zeit(MI - timedelta(days=1), 11)),
    ]
    ganz, zeitlich = termine_am_tag(termine, MI, TZ)
    assert [t.titel for t in ganz] == ["Geburtstag"]
    assert [(t.titel, s, e) for t, s, e in zeitlich] == [("Meeting", 600, 690)]


def test_ganztaegiges_ende_ist_exklusiv():
    urlaub = ganztags("Urlaub", date(2026, 10, 26), date(2026, 10, 31))
    assert termine_am_tag([urlaub], date(2026, 10, 30), TZ)[0] == [urlaub]
    assert termine_am_tag([urlaub], date(2026, 10, 31), TZ)[0] == []


def test_termin_ueber_mitternacht_wird_je_tag_zugeschnitten():
    party = termin("Party", zeit(MI, 22), zeit(MI + timedelta(days=1), 2))
    assert termine_am_tag([party], MI, TZ)[1][0][1:] == (1320, 1440)
    assert termine_am_tag([party], MI + timedelta(days=1), TZ)[1][0][1:] == (0, 120)


def test_termin_ohne_dauer_erscheint_am_starttag():
    erinnerung = termin("Erinnerung", zeit(MI, 9), zeit(MI, 9))
    assert len(termine_am_tag([erinnerung], MI, TZ)[1]) == 1


def test_spalten_ueberlappende_termine_nebeneinander():
    a, b, c, d = (termin(n, zeit(MI, 0), zeit(MI, 0)) for n in "abcd")
    ergebnis = spalten_verteilen([
        (a, 600, 690),   # 10:00–11:30
        (b, 660, 720),   # 11:00–12:00 überlappt a
        (c, 700, 760),   # 11:40–12:40 überlappt b, a ist frei → Spalte 0
        (d, 900, 960),   # 15:00 eigene Gruppe
    ])
    lage = {t.titel: (spalte, anzahl) for t, _, _, spalte, anzahl in ergebnis}
    assert lage == {"a": (0, 2), "b": (1, 2), "c": (0, 2), "d": (0, 1)}


def test_spalten_kurze_termine_bekommen_mindesthoehe():
    a, b = termin("a", zeit(MI, 0), zeit(MI, 0)), termin("b", zeit(MI, 0), zeit(MI, 0))
    # a dauert 15 Minuten, wird aber 30 Minuten hoch gezeichnet und überlappt so b
    ergebnis = spalten_verteilen([(a, 555, 570), (b, 575, 600)])
    assert [anzahl for *_, anzahl in ergebnis] == [2, 2]


def test_stundenbereich_wird_fuer_fruehe_und_spaete_termine_erweitert():
    assert stundenbereich([[(None, 6 * 60 + 30, 7 * 60)]], 7, 21) == (6, 21)
    assert stundenbereich([[(None, 21 * 60, 22 * 60 + 15)]], 7, 21) == (7, 23)
    assert stundenbereich([], 22, 8) == (0, 24)


def test_wochen_titel_ueber_monatsgrenze():
    tage = [date(2026, 9, 28) + timedelta(days=i) for i in range(7)]
    assert wochen_titel(tage) == "28. Sept. – 4. Okt. 2026"
    tage = [date(2026, 10, 12) + timedelta(days=i) for i in range(7)]
    assert wochen_titel(tage) == "12.–18. Oktober 2026"


def test_farben():
    assert kontrastfarbe("#ffffff") == "#000000"
    assert kontrastfarbe("#2f6fde") == "#ffffff"
    assert kontrastfarbe("kaputt") == "#ffffff"
    assert termin_tint("#ffffff") == "#ffffff"
    assert termin_tint("#000000") == "#d1d1d1"


def test_baue_tag_mit_vorschau_und_jetzt_linie():
    jetzt = zeit(MI, 10, 30)
    termine = [
        termin("Meeting", zeit(MI, 10), zeit(MI, 11)),
        termin("Morgen früh", zeit(MI + timedelta(days=1), 8), zeit(MI + timedelta(days=1), 9)),
        ganztags("Ausflug", MI + timedelta(days=3), MI + timedelta(days=4)),
    ]
    daten = baue_tag(termine, jetzt, TZ, 8, 18)
    assert daten["titel"] == "Mittwoch"
    assert daten["untertitel"] == "14. Oktober 2026"
    assert daten["bloecke"][0]["oben"] == pytest.approx(20.0)  # 10 Uhr bei 8–18 Uhr
    assert daten["jetzt"] == pytest.approx(25.0)
    assert [g["label"] for g in daten["vorschau"]] == ["Morgen", "Samstag, 17. Okt."]
    assert daten["vorschau"][0]["termine"][0]["zeit"] == "8:00"
    assert daten["vorschau"][1]["termine"][0]["zeit"] == ""
    assert not daten["leer"]


def test_baue_tag_ohne_termine_ist_leer():
    daten = baue_tag([], zeit(MI, 6), TZ)
    assert daten["leer"]
    assert daten["jetzt"] is None  # 6 Uhr liegt vor dem Zeitraum 7–21 Uhr


def test_baue_woche_markiert_heute_und_blendet_wochenende_aus():
    jetzt = zeit(MI, 12)
    daten = baue_woche([], jetzt, TZ, wochenstart=0)
    assert daten["titel"] == "KW 42"
    assert [s["kurz"] for s in daten["spalten"]] == ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    assert [s["heute"] for s in daten["spalten"]].index(True) == 2
    assert daten["spalten"][0]["vergangen"]

    ohne_we = baue_woche([], jetzt, TZ, wochenende=False)
    assert [s["kurz"] for s in ohne_we["spalten"]] == ["Mo", "Di", "Mi", "Do", "Fr"]

    ab_sonntag = baue_woche([], jetzt, TZ, wochenstart=6)
    assert ab_sonntag["spalten"][0]["kurz"] == "So"


def test_baue_woche_ohne_heute_hat_keine_jetzt_linie():
    samstag = zeit(date(2026, 10, 17), 12)
    daten = baue_woche([], samstag, TZ, wochenende=False)
    assert daten["jetzt"] is None


def test_baue_monat():
    termine = [termin("Zahnarzt", zeit(date(2026, 10, 22), 8), zeit(date(2026, 10, 22), 9))]
    daten = baue_monat(termine, zeit(MI, 9), TZ)
    assert daten["titel"] == "Oktober"
    assert daten["kopf"][0] == "Mo"
    zellen = [z for woche in daten["wochen"] for z in woche]
    assert zellen[0]["anderer_monat"] and zellen[0]["nummer"] == 28
    heute = [z for z in zellen if z["heute"]]
    assert len(heute) == 1 and heute[0]["nummer"] == 14
    zahnarzt = [z for z in zellen if z["termine"]]
    assert zahnarzt[0]["nummer"] == 22
    assert zahnarzt[0]["termine"][0]["zeit"] == "8:00"

    ohne_we = baue_monat([], zeit(MI, 9), TZ, wochenende=False)
    assert ohne_we["kopf"] == ["Mo", "Di", "Mi", "Do", "Fr"]
    assert all(len(w) == 5 for w in ohne_we["wochen"])


# --- iCal-Auswertung (braucht die Laufzeit-Abhängigkeiten) ---

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:1
DTSTART;TZID=America/New_York:20261014T040000
DTEND;TZID=America/New_York:20261014T050000
SUMMARY:Telefonat USA
END:VEVENT
BEGIN:VEVENT
UID:2
DTSTART;VALUE=DATE:20261015
SUMMARY:Ganztag ohne Ende
END:VEVENT
BEGIN:VEVENT
UID:3
DTSTART;TZID=Europe/Berlin:20261012T091500
DTEND;TZID=Europe/Berlin:20261012T093000
RRULE:FREQ=DAILY;COUNT=5
SUMMARY:Stand-up
END:VEVENT
BEGIN:VEVENT
UID:4
DTSTART:20261016T100000
DURATION:PT90M
SUMMARY:Floating
STATUS:CANCELLED
END:VEVENT
BEGIN:VEVENT
UID:5
DTSTART:20261016T120000
DURATION:PT90M
END:VEVENT
END:VCALENDAR
"""


def test_ics_wird_in_termine_umgewandelt(monkeypatch):
    for modul in ("icalendar", "recurring_ical_events", "requests", "PIL", "jinja2"):
        pytest.importorskip(modul)
    import icalendar
    from plugins.icloud_kalender.icloud_kalender import ICloudKalender

    monkeypatch.setattr(ICloudKalender, "abrufen", staticmethod(lambda url: icalendar.Calendar.from_ical(ICS)))
    plugin = ICloudKalender({"id": "icloud_kalender"})
    kalender = [{"url": "x", "name": "Arbeit", "farbe": "#2f6fde"}]
    termine, fehler = plugin.lade_termine(kalender, TZ, date(2026, 10, 12), date(2026, 10, 19))

    assert fehler == []
    nach_titel = {}
    for t in termine:
        nach_titel.setdefault(t.titel, []).append(t)
    assert len(nach_titel["Stand-up"]) == 5
    usa = nach_titel["Telefonat USA"][0]
    assert (usa.start.hour, usa.ende.hour) == (10, 11)  # in Berliner Zeit umgerechnet
    ganz = nach_titel["Ganztag ohne Ende"][0]
    assert ganz.ganztag and ganz.ende - ganz.start == timedelta(days=1)
    assert "Floating" not in nach_titel  # abgesagt
    ohne_titel = nach_titel["(Ohne Titel)"][0]
    assert (ohne_titel.start.hour, ohne_titel.ende.hour, ohne_titel.ende.minute) == (12, 13, 30)
    assert ohne_titel.kalender == "Arbeit"


def test_nicht_erreichbarer_kalender_wird_als_fehler_gemeldet(monkeypatch):
    for modul in ("icalendar", "recurring_ical_events", "requests", "PIL", "jinja2"):
        pytest.importorskip(modul)
    from plugins.icloud_kalender.icloud_kalender import ICloudKalender

    def kaputt(url):
        raise RuntimeError("404")

    monkeypatch.setattr(ICloudKalender, "abrufen", staticmethod(kaputt))
    plugin = ICloudKalender({"id": "icloud_kalender"})
    termine, fehler = plugin.lade_termine([{"url": "x", "name": "", "farbe": "#000"}], TZ,
                                          date(2026, 10, 12), date(2026, 10, 13))
    assert termine == [] and fehler == ["404"]


def test_kalender_liste_aus_einstellungen():
    for modul in ("icalendar", "recurring_ical_events", "requests", "PIL", "jinja2"):
        pytest.importorskip(modul)
    from plugins.icloud_kalender.icloud_kalender import ICloudKalender

    liste = ICloudKalender.kalender_liste({
        "kalenderURLs[]": ["webcal://a/1", "  ", "https://b/2"],
        "kalenderNamen[]": ["Privat", "", " Arbeit "],
        "kalenderFarben[]": ["#ff0000", "#00ff00", ""],
    })
    assert liste == [
        {"url": "https://a/1", "name": "Privat", "farbe": "#ff0000"},
        {"url": "https://b/2", "name": "Arbeit", "farbe": "#2f6fde"},
    ]
