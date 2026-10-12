import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

# Die Plugins importieren relativ zu src/ (wie beim Start von InkyPi)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from plugins.icloud_kalender.icloud_caldav import (  # noqa: E402
    CalDAVFehler, ICloudCalDAV, apple_farbe, waehle_kalender,
)
from plugins.icloud_kalender.kalender_daten import (  # noqa: E402
    EINK_PALETTEN, Termin, ansicht_aus, baue_naechstes, baue_tagesblatt, baue_wochenzettel,
    countdown, eink_palette, kalender_pastelle, naechste_farbe, normalisiere_url, spanne, tag_kurz,
    termine_am_tag, zeitraum,
)

TZ = ZoneInfo("Europe/Berlin")


def zeit(tag, stunde, minute=0):
    return datetime(tag.year, tag.month, tag.day, stunde, minute, tzinfo=TZ)


def termin(titel, start, ende, ganztag=False, farbe="#2f6fde"):
    return Termin(titel=titel, start=start, ende=ende, ganztag=ganztag, farbe=farbe)


def ganztags(titel, von, bis_exklusiv):
    return termin(titel, zeit(von, 0), zeit(bis_exklusiv, 0), ganztag=True)


MO = date(2026, 10, 12)  # Montag
MI = date(2026, 10, 14)  # Mittwoch


def tag(n):
    return MO + timedelta(days=n)


def beispiel():
    """Eine Woche wie bei Max: Ferien, Urlaub, ein Turnier ab morgen, Training."""
    return [
        ganztags("Ferien", date(2026, 10, 5), tag(6)),          # bis Sa
        ganztags("Urlaub", MO, tag(5)),                         # bis Fr
        ganztags("Denmark Open", tag(1), tag(7)),               # Di–So
        ganztags("Hamburg", tag(2), tag(3)),                    # Mi, eintägig
        termin("Zahnarzt", zeit(MO, 8, 15), zeit(MO, 9)),
        termin("Essen bei Toni", zeit(MO, 12), zeit(MO, 13, 30)),
        termin("Klavier", zeit(MO, 15, 5), zeit(MO, 15, 50)),
        termin("Elternabend", zeit(MO, 19, 30), zeit(MO, 21)),
        termin("Max Training", zeit(tag(1), 18), zeit(tag(1), 19, 30)),
        termin("Mariella Training", zeit(tag(1), 19, 30), zeit(tag(1), 21)),
        termin("Masked Singer", zeit(tag(2), 20, 15), zeit(tag(2), 22)),
        termin("Winterreifen", zeit(tag(4), 8), zeit(tag(4), 16)),
        termin("Training", zeit(tag(7), 18, 45), zeit(tag(7), 20)),
    ]


def test_webcal_link_wird_zu_https():
    assert normalisiere_url(" webcal://p1-caldav.icloud.com/published/2/abc ") == \
        "https://p1-caldav.icloud.com/published/2/abc"
    assert normalisiere_url("WEBCAL://x.de/a.ics") == "https://x.de/a.ics"
    assert normalisiere_url("https://x.de/a.ics") == "https://x.de/a.ics"
    assert normalisiere_url(None) == ""


def test_ansicht_aus_einstellung_und_alte_werte():
    assert ansicht_aus(None) == "naechstes"
    assert ansicht_aus("wochenzettel") == "wochenzettel"
    # Frühere Rasteransichten aus gespeicherten Instanzen
    assert ansicht_aus("tag") == "tagesblatt"
    assert ansicht_aus("woche") == "wochenzettel"
    assert ansicht_aus("monat") == "wochenzettel"
    assert ansicht_aus("jahr") == "naechstes"


def test_zeitraum_acht_tage_ab_heute():
    assert zeitraum(MI) == (MI, MI + timedelta(days=8))


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


def test_kurze_texte():
    assert countdown(0) == "gleich"
    assert countdown(20) == "in 20 Min."
    assert countdown(60) == "in 1 Std."
    assert countdown(80.5) == "in 1 Std. 20 Min."
    assert [tag_kurz(tag(i), MO) for i in (0, 1, 5, 7)] == ["heute", "morgen", "Sa", "19.10."]
    ferien, urlaub, turnier = beispiel()[:3]
    assert spanne(ferien, MO, TZ) == "bis Sa"
    assert spanne(urlaub, MO, TZ) == "bis Fr"
    assert spanne(turnier, MO, TZ) == "Di–So"
    assert spanne(ganztags("Messe", tag(3), tag(10)), MO, TZ) == "ab Do"


def test_als_naechstes_zeigt_den_naechsten_termin_gross():
    daten = baue_naechstes(beispiel(), zeit(MO, 11), TZ)
    assert (daten["wochentag"], daten["datum"]) == ("Montag", "12. Oktober")
    assert [(g["titel"], g["spanne"]) for g in daten["ganztag"]] == [("Ferien", "bis Sa"), ("Urlaub", "bis Fr")]
    held = daten["held"]
    assert (held["label"], held["zeit"], held["titel"], held["wann"]) == ("Als Nächstes", "12:00", "Essen bei Toni", "in 1 Std.")
    assert daten["held_heute"]
    # Vorbei (Zahnarzt) und der große Termin selbst stehen nicht mehr in der Liste
    assert [(t["zeit"], t["titel"]) for t in daten["spaeter"]] == [("15:05", "Klavier"), ("19:30", "Elternabend")]
    # Morgen: das neu beginnende Turnier, dann die Uhrzeiten
    assert [(t["zeit"], t["titel"]) for t in daten["morgen"]] == [
        ("", "Denmark Open"), ("18:00", "Max Training"), ("19:30", "Mariella Training")]


def test_als_naechstes_laufender_termin_und_morgen():
    daten = baue_naechstes(beispiel(), zeit(MO, 12, 30), TZ)
    assert daten["held"]["label"] == "Läuft gerade"
    assert daten["held"]["wann"] == "noch bis 13:30"

    # Abends: der nächste Termin ist morgen, „Später heute“ entfällt
    daten = baue_naechstes(beispiel(), zeit(MO, 21, 30), TZ)
    assert (daten["held"]["titel"], daten["held"]["wann"]) == ("Max Training", "Morgen")
    assert not daten["held_heute"] and daten["spaeter"] == []
    assert [t["titel"] for t in daten["morgen"]] == ["Denmark Open", "Mariella Training"]

    leer = baue_naechstes([], zeit(MO, 9), TZ)
    assert leer["held"] is None and leer["morgen"] == []


def test_wochenzettel_acht_tage_ab_heute():
    daten = baue_wochenzettel(beispiel(), zeit(MO, 11), TZ)
    assert (daten["monat"], daten["bereich"], daten["kw"]) == ("Oktober", "12.–19. Oktober", 42)
    # Mehrtägige Ganztagstermine einmal oben, nicht an jedem Tag
    assert [(b["titel"], b["spanne"]) for b in daten["band"]] == [
        ("Ferien", "bis Sa"), ("Urlaub", "bis Fr"), ("Denmark Open", "Di–So")]
    tage = daten["tage"]
    assert [t["kurz"] for t in tage] == ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So", "Mo"]
    assert tage[0]["heute"] and not tage[1]["heute"]
    assert [(e["zeit"], e["titel"], e["vorbei"]) for e in tage[0]["termine"]] == [
        ("8:15", "Zahnarzt", True), ("12:00", "Essen bei Toni", False),
        ("15:05", "Klavier", False), ("19:30", "Elternabend", False)]
    assert [(e["zeit"], e["titel"]) for e in tage[2]["termine"]] == [("", "Hamburg"), ("20:15", "Masked Singer")]
    assert tage[3]["termine"] == []
    assert [e["titel"] for e in tage[7]["termine"]] == ["Training"]


def test_wochenzettel_ueber_monatsgrenze_und_mitternacht():
    heute = date(2026, 10, 28)
    party = termin("Party", zeit(heute, 22), zeit(heute + timedelta(days=1), 2))
    daten = baue_wochenzettel([party], zeit(heute, 9), TZ)
    assert daten["bereich"] == "28. Okt. – 4. Nov."
    # Am Folgetag ohne Uhrzeit, weil der Termin schon am Vortag begonnen hat
    assert [(e["zeit"], e["titel"]) for e in daten["tage"][1]["termine"]] == [("", "Party")]


def test_tagesblatt():
    daten = baue_tagesblatt(beispiel(), zeit(MO, 12, 30), TZ)
    assert (daten["wochentag"], daten["nummer"], daten["monat"]) == ("Montag", 12, "Oktober")
    assert [(g["titel"], g["spanne"]) for g in daten["ganztag"]] == [("Ferien", "bis Sa"), ("Urlaub", "bis Fr")]
    assert [(t["zeit"], t["vorbei"], t["laeuft"], t["naechst"], t["wann"]) for t in daten["termine"]] == [
        ("8:15", True, False, False, ""), ("12:00", False, True, True, "noch bis 13:30"),
        ("15:05", False, False, False, ""), ("19:30", False, False, False, "")]
    assert (daten["jahr"], daten["jetzt"]) == (2026, "12:30")
    # Vor dem Termin: Countdown statt „noch bis“
    assert baue_tagesblatt(beispiel(), zeit(MO, 11), TZ)["termine"][1]["wann"] == "in 1 Std."
    assert daten["morgen"] == ["Denmark Open", "18:00 Max Training", "19:30 Mariella Training"]

    leer = baue_tagesblatt([], zeit(MO, 9), TZ)
    assert leer["termine"] == [] and leer["morgen"] == [] and leer["ganztag"] == []


def test_eink_palette_je_display():
    assert eink_palette("inky") == EINK_PALETTEN["inky"]
    assert eink_palette("epd7in3f") == EINK_PALETTEN["waveshare"]
    assert eink_palette("") == EINK_PALETTEN["waveshare"]


def test_farben_werden_auf_displayfarben_gesetzt():
    inky = EINK_PALETTEN["inky"]
    rot, gruen, blau, gelb, orange = "#cd2425", "#1dad23", "#1e1dae", "#e7de23", "#d87b24"
    assert naechste_farbe("#e0393e", inky) == rot
    assert naechste_farbe("#2f6fde", inky) == blau
    assert naechste_farbe("#1f9d55", inky) == gruen
    assert naechste_farbe("#f08c00", inky) == orange
    assert naechste_farbe("#ffd60a", inky) == gelb
    assert naechste_farbe("#111418", inky) == "#1c181c"
    # Weiß wäre auf weißem Grund unsichtbar
    assert naechste_farbe("#ffffff", inky) != "#ffffff"
    assert all(naechste_farbe(f, inky) == f for f in inky)


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


# --- iCloud per CalDAV (mit nachgebautem Server) ---

def multistatus(*antworten):
    return ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" '
            'xmlns:a="http://apple.com/ns/ical/">' + "".join(antworten) + "</d:multistatus>")


def antwort(href, props, fehlend=""):
    xml = f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>{props}</d:prop>" \
          "<d:status>HTTP/1.1 200 OK</d:status></d:propstat>"
    if fehlend:
        xml += f"<d:propstat><d:prop>{fehlend}</d:prop><d:status>HTTP/1.1 404 Not Found</d:status></d:propstat>"
    return xml + "</d:response>"


HOME = "https://p42-caldav.icloud.com:443/1234/calendars/"
KALENDER_ORDNER = multistatus(
    antwort("/1234/calendars/", "<d:resourcetype><d:collection/></d:resourcetype>"),
    antwort("/1234/calendars/home/",
            "<d:displayname>Privat</d:displayname><a:calendar-color>#FF2968FF</a:calendar-color>"
            "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
            '<c:supported-calendar-component-set><c:comp name="VEVENT"/></c:supported-calendar-component-set>'),
    antwort("/1234/calendars/work/",
            "<d:displayname>Arbeit</d:displayname>"
            "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>",
            fehlend="<a:calendar-color/>"),
    antwort("/1234/calendars/tasks/",
            "<d:displayname>Erinnerungen</d:displayname>"
            "<d:resourcetype><d:collection/><c:calendar/></d:resourcetype>"
            '<c:supported-calendar-component-set><c:comp name="VTODO"/></c:supported-calendar-component-set>'),
    antwort("/1234/calendars/inbox/", "<d:resourcetype><d:collection/><c:schedule-inbox/></d:resourcetype>"),
)


class Antwort:
    def __init__(self, status, text, url):
        self.status_code, self.text, self.url = status, text, url


class ICloudAttrappe:
    """Antwortet wie caldav.icloud.com und merkt sich die Anfragen."""

    def __init__(self, status=207):
        self.status = status
        self.anfragen = []

    def request(self, methode, url, data=None, headers=None, auth=None, timeout=None):
        body = data.decode()
        self.anfragen.append((methode, url, headers["Depth"], body, auth))
        if self.status != 207:
            return Antwort(self.status, "", url)
        if methode == "PROPFIND" and "current-user-principal" in body:
            return Antwort(207, multistatus(antwort("/", "<d:current-user-principal><d:href>/1234/principal/"
                                                         "</d:href></d:current-user-principal>")), url)
        if methode == "PROPFIND" and "calendar-home-set" in body:
            return Antwort(207, multistatus(antwort("/1234/principal/", "<c:calendar-home-set><d:href>"
                                                    f"{HOME}</d:href></c:calendar-home-set>")), url)
        if methode == "PROPFIND":
            return Antwort(207, KALENDER_ORDNER, url)
        if methode == "REPORT":
            return Antwort(207, multistatus(
                antwort("/1234/calendars/home/a.ics", f"<c:calendar-data>{ICS.decode()}</c:calendar-data>"),
                antwort("/1234/calendars/home/b.ics", "<c:calendar-data></c:calendar-data>"),
            ), url)
        raise AssertionError(methode)


def test_caldav_findet_kalender_mit_namen_und_farben():
    server = ICloudAttrappe()
    kalender = ICloudCalDAV(server, "ich@icloud.com", "abcd-efgh").kalender()
    assert kalender == [
        {"url": HOME + "home/", "name": "Privat", "farbe": "#ff2968"},
        {"url": HOME + "work/", "name": "Arbeit", "farbe": None},
    ]
    urls = [a[1] for a in server.anfragen]
    assert urls == ["https://caldav.icloud.com/", "https://caldav.icloud.com/1234/principal/", HOME]
    assert all(a[4] == ("ich@icloud.com", "abcd-efgh") for a in server.anfragen)
    assert [a[2] for a in server.anfragen] == ["0", "0", "1"]


def test_caldav_holt_termine_im_zeitraum():
    server = ICloudAttrappe()
    client = ICloudCalDAV(server, "ich", "pw")
    daten = client.termine_ical(HOME + "home/", zeit(MI, 0), zeit(MI + timedelta(days=7), 0))
    assert len(daten) == 1 and "Telefonat USA" in daten[0]
    methode, _, tiefe, body, _ = server.anfragen[0]
    assert (methode, tiefe) == ("REPORT", "1")
    # Berliner Mitternacht ist im Oktober 22 Uhr UTC am Vortag
    assert 'start="20261013T220000Z"' in body and 'end="20261020T220000Z"' in body


def test_caldav_falsches_passwort():
    with pytest.raises(CalDAVFehler, match="app-spezifisches Passwort"):
        ICloudCalDAV(ICloudAttrappe(status=401), "ich", "falsch").kalender()
    with pytest.raises(CalDAVFehler, match="503"):
        ICloudCalDAV(ICloudAttrappe(status=503), "ich", "pw").kalender()


def test_apple_farbe():
    assert apple_farbe("#FF2968FF") == "#ff2968"
    assert apple_farbe("#1BADF8") == "#1badf8"
    assert apple_farbe("") is None
    assert apple_farbe("rot") is None


def test_kalenderauswahl_nach_namen():
    alle = [{"name": "Privat"}, {"name": "Arbeit"}, {"name": "Familie"}]
    assert waehle_kalender(alle, "") == alle
    assert waehle_kalender(alle, []) == alle
    assert waehle_kalender(alle, " familie, Privat ") == [{"name": "Familie"}, {"name": "Privat"}]
    with pytest.raises(CalDAVFehler, match="nicht gefunden: „Urlaub“ .vorhanden: „Privat“, „Arbeit“, „Familie“"):
        waehle_kalender(alle, "Privat, Urlaub")


ECHTE_NAMEN = [{"name": n} for n in (
    "Teneriffa (Max, Nicole & Mariella)", "Nicole Kalender (Ersatz print)", "Job, Sport & Co",
    "Schule KL/VK-Test/HA-Kontrolle", "Termine rund um Louis, Max & Mariella", "Date Max & Nicole", "Privat",
)]


def test_kalendernamen_mit_komma_als_liste():
    gewaehlt = waehle_kalender(ECHTE_NAMEN, ["Job, Sport & Co", "Privat", "job, sport & co"])
    assert [k["name"] for k in gewaehlt] == ["Job, Sport & Co", "Privat"]


def test_alte_komma_auswahl_mit_kommanamen():
    # So stand es nach zweimaligem Antippen in den Einstellungen
    gewaehlt = waehle_kalender(ECHTE_NAMEN, "Job, Sport & Co, Job, Sport & Co")
    assert [k["name"] for k in gewaehlt] == ["Job, Sport & Co"]
    gewaehlt = waehle_kalender(ECHTE_NAMEN, "Privat, Teneriffa (Max, Nicole & Mariella),job,sport & co")
    assert [k["name"] for k in gewaehlt] == ["Privat", "Teneriffa (Max, Nicole & Mariella)", "Job, Sport & Co"]
    with pytest.raises(CalDAVFehler, match="„Job“"):
        waehle_kalender(ECHTE_NAMEN, "Job")


def test_icloud_auswahl_aus_einstellungen():
    for modul in ("icalendar", "recurring_ical_events", "requests", "PIL", "jinja2"):
        pytest.importorskip(modul)
    from plugins.icloud_kalender.icloud_kalender import ICloudKalender

    auswahl = ICloudKalender.icloud_auswahl
    # Ältere Einstellungen gehören zu Konto 1
    assert auswahl({"icloudKalender[]": ["Job, Sport & Co"], "icloudKalender": "x"}) == {1: ["Job, Sport & Co"]}
    assert auswahl({"icloudKalender[]": "Privat"}) == {1: ["Privat"]}
    assert auswahl({"icloudKalender": "Privat, Arbeit"}) == {1: "Privat, Arbeit"}
    assert auswahl({}) == {}
    assert auswahl({"icloudKalender[]": []}) == {}
    # Mehrere Konten: Namen und Kontonummern als gleich lange Listen
    assert auswahl({"icloudKalender[]": ["Privat", "Privat", "Job, Sport & Co"],
                    "icloudKonto[]": ["1", "2", "1"]}) == {1: ["Privat", "Job, Sport & Co"], 2: ["Privat"]}
    assert auswahl({"icloudKalender[]": "Privat", "icloudKonto[]": "3"}) == {3: ["Privat"]}
    assert auswahl({"icloudKalender[]": ["A", "B"], "icloudKonto[]": ["9"]}) == {1: ["A", "B"]}


class Geraet:
    def __init__(self, env):
        self.env = env

    def load_env_key(self, key):
        return self.env.get(key)


def test_icloud_konto_im_plugin(monkeypatch):
    for modul in ("icalendar", "recurring_ical_events", "requests", "PIL", "jinja2"):
        pytest.importorskip(modul)
    import requests
    from plugins.icloud_kalender.icloud_kalender import ICloudKalender

    server = ICloudAttrappe()
    monkeypatch.setattr(requests, "Session", lambda: server)
    plugin = ICloudKalender({"id": "icloud_kalender"})
    start, ende = zeit(date(2026, 10, 12), 0), zeit(date(2026, 10, 19), 0)

    with pytest.raises(RuntimeError, match="Zugangsdaten"):
        plugin.icloud_kalender({}, Geraet({}), start, ende)

    geraet = Geraet({"ICLOUD_APPLE_ID": " ich@icloud.com ", "ICLOUD_APP_PASSWORT": "pw"})
    kalender, fehler = plugin.icloud_kalender({"icloudKalender": "Arbeit, Privat"}, geraet, start, ende)
    assert fehler == []
    assert [(k["name"], k["farbe"]) for k in kalender] == [("Arbeit", "#2f6fde"), ("Privat", "#ff2968")]

    termine, fehler = plugin.lade_termine(kalender, TZ, date(2026, 10, 12), date(2026, 10, 19))
    assert fehler == []
    titel = sorted({t.titel for t in termine if t.kalender == "Privat"})
    assert "Telefonat USA" in titel and "Stand-up" in titel
    assert server.anfragen[0][4] == ("ich@icloud.com", "pw")


class ZweiKonten(ICloudAttrappe):
    """Ein Server für mehrere Apple-IDs; `gesperrt` bekommt „falsches Passwort“."""

    def __init__(self, gesperrt=()):
        super().__init__()
        self.gesperrt = gesperrt

    def request(self, methode, url, data=None, headers=None, auth=None, timeout=None):
        if auth[0] in self.gesperrt:
            self.anfragen.append((methode, url, headers["Depth"], data.decode(), auth))
            return Antwort(401, "", url)
        return super().request(methode, url, data, headers, auth, timeout)


ZWEI_KONTEN = {
    "ICLOUD_APPLE_ID": "max@icloud.com", "ICLOUD_APP_PASSWORT": "pw1",
    "ICLOUD_APPLE_ID_2": "nicole@icloud.com", "ICLOUD_APP_PASSWORT_2": "pw2", "ICLOUD_KONTO_NAME_2": "Nicole",
}


def test_icloud_konten_aus_env():
    from zugangsdaten import icloud_konten, icloud_schluessel

    assert icloud_schluessel(1)["apple_id"] == "ICLOUD_APPLE_ID"
    assert icloud_schluessel(3)["passwort"] == "ICLOUD_APP_PASSWORT_3"
    konten = icloud_konten(ZWEI_KONTEN.get)
    assert [(k["nr"], k["name"], k["apple_id"], k["passwort"]) for k in konten] == [
        (1, "iCloud-Konto 1", "max@icloud.com", "pw1"), (2, "Nicole", "nicole@icloud.com", "pw2")]
    # Ohne Passwort zählt ein Konto nicht
    assert [k["nr"] for k in icloud_konten({**ZWEI_KONTEN, "ICLOUD_APP_PASSWORT": " "}.get)] == [2]
    assert icloud_konten({}.get) == []


def test_mehrere_icloud_konten_im_plugin(monkeypatch):
    for modul in ("icalendar", "recurring_ical_events", "requests", "PIL", "jinja2"):
        pytest.importorskip(modul)
    import requests
    from plugins.icloud_kalender.icloud_kalender import ICloudKalender

    server = ZweiKonten()
    monkeypatch.setattr(requests, "Session", lambda: server)
    plugin = ICloudKalender({"id": "icloud_kalender"})
    start, ende = zeit(date(2026, 10, 12), 0), zeit(date(2026, 10, 19), 0)

    # Leere Auswahl: alle Kalender aller Konten
    kalender, fehler = plugin.icloud_kalender({}, Geraet(ZWEI_KONTEN), start, ende)
    assert fehler == [] and [k["name"] for k in kalender] == ["Privat", "Arbeit", "Privat", "Arbeit"]

    # Gleichnamige Kalender werden über das Konto unterschieden
    einstellungen = {"icloudKalender[]": ["Privat", "Arbeit"], "icloudKonto[]": ["2", "1"]}
    kalender, fehler = plugin.icloud_kalender(einstellungen, Geraet(ZWEI_KONTEN), start, ende)
    # Reihenfolge nach Konto
    assert fehler == [] and [k["name"] for k in kalender] == ["Arbeit", "Privat"]
    server.anfragen.clear()
    termine, _ = plugin.lade_termine(kalender[1:], TZ, date(2026, 10, 12), date(2026, 10, 19))
    assert termine and {a[4] for a in server.anfragen} == {("nicole@icloud.com", "pw2")}

    # Nur Konto 1 ausgewählt: Konto 2 wird gar nicht abgefragt
    server.anfragen.clear()
    kalender, _ = plugin.icloud_kalender({"icloudKalender[]": ["Arbeit"], "icloudKonto[]": ["1"]},
                                         Geraet(ZWEI_KONTEN), start, ende)
    assert [k["name"] for k in kalender] == ["Arbeit"]
    assert {a[4][0] for a in server.anfragen} == {"max@icloud.com"}


def test_ein_kaputtes_konto_stoert_die_anderen_nicht(monkeypatch):
    for modul in ("icalendar", "recurring_ical_events", "requests", "PIL", "jinja2"):
        pytest.importorskip(modul)
    import requests
    from plugins.icloud_kalender.icloud_kalender import ICloudKalender

    monkeypatch.setattr(requests, "Session", lambda: ZweiKonten(gesperrt=("nicole@icloud.com",)))
    plugin = ICloudKalender({"id": "icloud_kalender"})
    start, ende = zeit(date(2026, 10, 12), 0), zeit(date(2026, 10, 19), 0)

    kalender, fehler = plugin.icloud_kalender({}, Geraet(ZWEI_KONTEN), start, ende)
    assert [k["name"] for k in kalender] == ["Privat", "Arbeit"]
    assert len(fehler) == 1 and fehler[0].startswith("Nicole: iCloud-Anmeldung fehlgeschlagen")

    # Ausgewähltes Konto, dessen Zugangsdaten inzwischen gelöscht wurden
    einstellungen = {"icloudKalender[]": ["Privat", "Privat"], "icloudKonto[]": ["1", "3"]}
    kalender, fehler = plugin.icloud_kalender(einstellungen, Geraet(ZWEI_KONTEN), start, ende)
    assert [k["name"] for k in kalender] == ["Privat"]
    assert fehler == ["iCloud-Konto 3: Zugangsdaten fehlen – bitte unter Einstellungen → Zugangsdaten eintragen"]

    # Nur das kaputte Konto ausgewählt: Fehler wie bisher
    with pytest.raises(RuntimeError, match="Nicole: iCloud-Anmeldung"):
        plugin.icloud_kalender({"icloudKalender[]": ["Privat"], "icloudKonto[]": ["2"]},
                               Geraet(ZWEI_KONTEN), start, ende)


def test_kalender_bekommen_eigene_pastelltoene():
    # Max' Kalender: zwei orange, Braun, Gelb, Violett, Grün
    toene = kalender_pastelle(["#ff9500", "#a2845e", "#ffcc00", "#ff9500", "#cc73e1", "#63da38"])
    assert toene[0] == "apricot" and toene[2] == "hellgelb" and toene[4] == "himmel" and toene[5] == "mint"
    assert len(set(toene)) == 6
    assert kalender_pastelle(["#ff2968", "#1badf8", "#000000"]) == ["rosa", "himmel", "hellgrau"]
    # Mehr Kalender als Töne: dann teilen sie sich Töne
    assert len(kalender_pastelle(["#ff0000"] * 9)) == 9
    assert kalender_pastelle([]) == []


def test_eintraege_tragen_die_kalenderfarbe():
    termine = beispiel()
    termine[4].farbe = "#123456"  # Zahnarzt
    termine[1].farbe = "#abcdef"  # Urlaub
    woche = baue_wochenzettel(termine, zeit(MO, 11), TZ)
    assert woche["tage"][0]["termine"][0]["farbe"] == "#123456"
    assert woche["band"][1]["farbe"] == "#abcdef"
    assert baue_tagesblatt(termine, zeit(MO, 11), TZ)["ganztag"][1]["farbe"] == "#abcdef"
