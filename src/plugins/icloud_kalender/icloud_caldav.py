"""Private iCloud-Kalender per CalDAV abrufen – ohne öffentlichen Link.

Anmeldung mit Apple-ID und einem app-spezifischen Passwort. Ablauf:
  1. PROPFIND auf caldav.icloud.com → Adresse des Benutzerkontos (principal)
  2. PROPFIND auf das Konto → Ordner mit allen Kalendern (calendar-home-set)
  3. PROPFIND auf den Ordner → Kalender mit Name und Farbe
  4. REPORT je Kalender → alle Termine im gewünschten Zeitraum (als iCal-Text)

Nur Standardbibliothek; die HTTP-Anfragen laufen über eine requests-Session,
die von außen übergeben wird (in Tests eine Attrappe).
"""

import xml.etree.ElementTree as ET
from datetime import timezone
from urllib.parse import urljoin

ICLOUD_CALDAV = "https://caldav.icloud.com/"
NS = {
    "d": "DAV:",
    "c": "urn:ietf:params:xml:ns:caldav",
    "a": "http://apple.com/ns/ical/",
}
TIMEOUT = 20

_PROPFIND = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav" xmlns:a="http://apple.com/ns/ical/">
  <d:prop>{props}</d:prop>
</d:propfind>"""

_REPORT = """<?xml version="1.0" encoding="utf-8"?>
<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
  <d:prop><c:calendar-data/></d:prop>
  <c:filter>
    <c:comp-filter name="VCALENDAR">
      <c:comp-filter name="VEVENT">
        <c:time-range start="{start}" end="{ende}"/>
      </c:comp-filter>
    </c:comp-filter>
  </c:filter>
</c:calendar-query>"""


class CalDAVFehler(RuntimeError):
    pass


def antworten(xml_text):
    """Zerlegt eine WebDAV-Multistatus-Antwort in (href, prop-Element)-Paare.

    Es zählen nur Eigenschaften mit Status 200; fehlende Eigenschaften (404)
    meldet iCloud in einem eigenen propstat-Block.
    """
    try:
        wurzel = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise CalDAVFehler(f"Ungültige Antwort vom Kalenderserver ({e})")
    ergebnis = []
    for antwort in wurzel.findall("d:response", NS):
        href = (antwort.findtext("d:href", default="", namespaces=NS) or "").strip()
        props = ET.Element("prop")
        for propstat in antwort.findall("d:propstat", NS):
            status = propstat.findtext("d:status", default="", namespaces=NS)
            if " 200 " in f"{status} ":
                prop = propstat.find("d:prop", NS)
                if prop is not None:
                    props.extend(list(prop))
        ergebnis.append((href, props))
    return ergebnis


def _href_in(prop, pfad):
    return (prop.findtext(f"{pfad}/d:href", default="", namespaces=NS) or "").strip()


def apple_farbe(wert):
    """iCloud liefert Farben als #RRGGBBAA – fürs Plugin reicht #RRGGBB."""
    wert = (wert or "").strip()
    if len(wert) in (7, 9) and wert.startswith("#"):
        return wert[:7].lower()
    return None


def kalender_aus_antwort(xml_text, basis_url):
    """Liest die Kalender (nur solche mit Terminen, keine Erinnerungslisten) aus."""
    kalender = []
    for href, prop in antworten(xml_text):
        typ = prop.find("d:resourcetype", NS)
        if typ is None or typ.find("c:calendar", NS) is None:
            continue
        komponenten = prop.find("c:supported-calendar-component-set", NS)
        if komponenten is not None:
            namen = {k.get("name", "").upper() for k in komponenten.findall("c:comp", NS)}
            if "VEVENT" not in namen:
                continue
        kalender.append({
            "url": urljoin(basis_url, href),
            "name": (prop.findtext("d:displayname", default="", namespaces=NS) or "").strip() or "iCloud",
            "farbe": apple_farbe(prop.findtext("a:calendar-color", default="", namespaces=NS)),
        })
    return kalender


def _utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class ICloudCalDAV:
    def __init__(self, session, apple_id, passwort, basis_url=ICLOUD_CALDAV):
        self.session = session
        self.auth = (apple_id, passwort)
        self.basis_url = basis_url

    def _anfrage(self, methode, url, body, tiefe):
        antwort = self.session.request(
            methode, url,
            data=body.encode("utf-8"),
            headers={"Depth": str(tiefe), "Content-Type": "application/xml; charset=utf-8"},
            auth=self.auth,
            timeout=TIMEOUT,
        )
        if antwort.status_code == 401:
            raise CalDAVFehler("iCloud-Anmeldung fehlgeschlagen – Apple-ID und app-spezifisches Passwort prüfen")
        if antwort.status_code >= 400:
            raise CalDAVFehler(f"iCloud antwortet mit Fehler {antwort.status_code}")
        return antwort.url or url, antwort.text

    def _propfind(self, url, props, tiefe=0):
        return self._anfrage("PROPFIND", url, _PROPFIND.format(props=props), tiefe)

    def kalender(self):
        url, text = self._propfind(self.basis_url, "<d:current-user-principal/>")
        principal = next((_href_in(p, "d:current-user-principal") for _, p in antworten(text)), "")
        if not principal:
            raise CalDAVFehler("iCloud-Konto nicht gefunden")
        principal = urljoin(url, principal)

        url, text = self._propfind(principal, "<c:calendar-home-set/>")
        home = next((_href_in(p, "c:calendar-home-set") for _, p in antworten(text)), "")
        if not home:
            raise CalDAVFehler("Kalenderordner im iCloud-Konto nicht gefunden")
        home = urljoin(url, home)

        url, text = self._propfind(
            home,
            "<d:displayname/><d:resourcetype/><a:calendar-color/><c:supported-calendar-component-set/>",
            tiefe=1,
        )
        return kalender_aus_antwort(text, url)

    def termine_ical(self, kalender_url, start, ende):
        """iCal-Texte aller Termine, die den Zeitraum [start, ende) berühren."""
        _, text = self._anfrage("REPORT", kalender_url, _REPORT.format(start=_utc(start), ende=_utc(ende)), 1)
        daten = []
        for _, prop in antworten(text):
            ical = prop.findtext("c:calendar-data", default="", namespaces=NS)
            if ical and ical.strip():
                daten.append(ical)
        return daten


def waehle_kalender(alle, auswahl):
    """Filtert nach den eingestellten Namen (Komma-getrennt, Groß/klein egal); leer = alle."""
    namen = [n.strip() for n in (auswahl or "").split(",") if n.strip()]
    if not namen:
        return alle
    nach_name = {k["name"].casefold(): k for k in alle}
    fehlend = [n for n in namen if n.casefold() not in nach_name]
    if fehlend:
        vorhanden = ", ".join(k["name"] for k in alle) or "keine"
        raise CalDAVFehler(f"iCloud-Kalender nicht gefunden: {', '.join(fehlend)} (vorhanden: {vorhanden})")
    return [nach_name[n.casefold()] for n in namen]
