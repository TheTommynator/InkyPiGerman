"""iCloud-Kalender: mehrere (iCloud-)Kalender als Tages-, Wochen- oder Monatsansicht.

Die Kalender werden über ihren öffentlichen iCal-Link abgerufen (in der
Kalender-App: Kalender teilen → „Öffentlicher Kalender“). Funktioniert ebenso
mit jedem anderen iCal-/ICS-Link, z. B. von Google oder Outlook.
"""

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import icalendar
import recurring_ical_events
import requests

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.icloud_kalender.kalender_daten import (
    ANSICHTEN, Termin, baue_monat, baue_tag, baue_woche, normalisiere_url,
    parse_stunde, tagesbeginn, zeitraum,
)

logger = logging.getLogger(__name__)

STANDARD_FARBE = "#2f6fde"
SCHRIFTGROESSEN = {"klein": 0.85, "normal": 1.0, "gross": 1.15, "sehr_gross": 1.3}
ABRUF_TIMEOUT = 20


class ICloudKalender(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["style_settings"] = False
        return template_params

    def generate_image(self, settings, device_config):
        ansicht = settings.get("ansicht") or "woche"
        if ansicht not in ANSICHTEN:
            raise RuntimeError("Ungültige Ansicht")

        kalender = self.kalender_liste(settings)
        if not kalender:
            raise RuntimeError("Bitte mindestens einen Kalender-Link angeben")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        tz = self.zeitzone(device_config.get_config("timezone", default="Europe/Berlin"))
        zeitformat = device_config.get_config("time_format", default="24h")
        jetzt = self.jetzt(tz)

        wochenstart = 6 if settings.get("wochenstart") == "6" else 0
        von_h = parse_stunde(settings.get("vonStunde"), 7)
        bis_h = parse_stunde(settings.get("bisStunde"), 21)
        wochenende = settings.get("wochenende", "true") != "false"

        von, bis = zeitraum(ansicht, jetzt.date(), wochenstart)
        termine, fehler = self.lade_termine(kalender, tz, von, bis)
        if fehler and len(fehler) == len(kalender):
            raise RuntimeError(f"Kalender konnte nicht abgerufen werden: {fehler[0]}")

        if ansicht == "tag":
            daten = baue_tag(termine, jetzt, tz, von_h, bis_h, zeitformat)
        elif ansicht == "woche":
            daten = baue_woche(termine, jetzt, tz, wochenstart, von_h, bis_h, zeitformat, wochenende)
        else:
            daten = baue_monat(termine, jetzt, tz, wochenstart, zeitformat, wochenende)

        breite, hoehe = dimensions
        skala = SCHRIFTGROESSEN.get(settings.get("schriftgroesse"), 1.0)
        template_params = {
            "ansicht": ansicht,
            "daten": daten,
            "kalender": [k for k in kalender if k["name"]],
            "legende": settings.get("legende", "true") != "false",
            "stil": settings.get("stil") or "gefuellt",
            "thema": settings.get("thema") or "hell",
            "akzent": settings.get("akzentfarbe") or "#e0393e",
            "basis_px": round((breite + hoehe) / 1280 * 15 * skala, 2),
            "hochformat": hoehe > breite,
            "fehler": len(fehler),
            "stand": f"{jetzt.hour}:{jetzt.minute:02d}",
            "plugin_settings": {},
        }

        image = self.render_image(dimensions, "icloud_kalender.html", "icloud_kalender.css", template_params)
        if not image:
            raise RuntimeError("Screenshot fehlgeschlagen, bitte Logs prüfen.")
        return image

    @staticmethod
    def jetzt(tz):
        return datetime.now(tz)

    @staticmethod
    def zeitzone(name):
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning(f"Unbekannte Zeitzone '{name}', nutze Europe/Berlin")
            return ZoneInfo("Europe/Berlin")

    @staticmethod
    def kalender_liste(settings):
        urls = settings.get("kalenderURLs[]") or []
        namen = settings.get("kalenderNamen[]") or []
        farben = settings.get("kalenderFarben[]") or []
        if isinstance(urls, str):
            urls, namen, farben = [urls], [namen], [farben]
        liste = []
        for i, url in enumerate(urls):
            url = normalisiere_url(url)
            if not url:
                continue
            liste.append({
                "url": url,
                "name": (namen[i] if i < len(namen) else "").strip(),
                "farbe": (farben[i] if i < len(farben) else "") or STANDARD_FARBE,
            })
        return liste

    def lade_termine(self, kalender, tz, von, bis):
        """Lädt alle Kalender; ein nicht erreichbarer Kalender bricht die Anzeige nicht ab."""
        termine, fehler = [], []
        start, ende = tagesbeginn(von, tz), tagesbeginn(bis, tz)
        for k in kalender:
            try:
                cal = self.abrufen(k["url"])
                for event in recurring_ical_events.of(cal).between(start, ende):
                    termin = self.zu_termin(event, k, tz)
                    if termin:
                        termine.append(termin)
            except Exception as e:
                logger.error(f"Kalender '{k['name'] or k['url']}' fehlgeschlagen: {e}")
                fehler.append(str(e))
        return termine, fehler

    @staticmethod
    def abrufen(url):
        response = requests.get(url, timeout=ABRUF_TIMEOUT, headers={"User-Agent": "InkyPi"})
        response.raise_for_status()
        return icalendar.Calendar.from_ical(response.content)

    @staticmethod
    def zu_termin(event, kalender, tz):
        if str(event.get("status", "")).upper() == "CANCELLED":
            return None

        def als_zeit(wert):
            if isinstance(wert, datetime):
                if wert.tzinfo is None:  # „floating“ Zeit = Ortszeit
                    return wert.replace(tzinfo=tz)
                return wert.astimezone(tz)
            return tagesbeginn(wert, tz)

        dtstart = event.decoded("dtstart")
        ganztag = isinstance(dtstart, date) and not isinstance(dtstart, datetime)
        start = als_zeit(dtstart)

        if "dtend" in event:
            ende = als_zeit(event.decoded("dtend"))
        elif "duration" in event:
            ende = start + event.decoded("duration")
        else:
            ende = start + timedelta(days=1) if ganztag else start
        if ende < start:
            ende = start

        return Termin(
            titel=str(event.get("summary", "")).strip() or "(Ohne Titel)",
            start=start,
            ende=ende,
            ganztag=ganztag,
            farbe=kalender["farbe"],
            kalender=kalender["name"],
            ort=str(event.get("location", "") or "").strip(),
        )
