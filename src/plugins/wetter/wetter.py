"""Wetter: aktuelle Lage, Stundenverlauf und Woche – klar und ohne API-Schlüssel.

Daten:
  - Vorhersage von Open-Meteo. Für Deutschland nutzt Open-Meteo automatisch
    die Modelle des Deutschen Wetterdienstes (ICON-D2/ICON-EU).
  - Amtliche Warnungen des DWD über Bright Sky (brightsky.dev). Fällt der
    Dienst aus, fehlt nur das Warnband.
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests

from plugins.base_plugin.base_plugin import BasePlugin
from plugins.icloud_kalender.kalender_daten import naechste_farbe
from utils.eink_farben import muster_einsetzen, palette, rollen_farben
from plugins.wetter.kunst_daten import poesie, szene_fenster
from plugins.wetter.wetter_daten import (
    ANSICHTEN, KUNST_ANSICHTEN, baue_ansicht, datum_text, lese_open_meteo, lese_warnungen, parse_details,
)
from plugins.wetter.wetter_icons import symbol, wetter_icon

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
BRIGHT_SKY_ALERTS_URL = "https://api.brightsky.dev/alerts"
ABRUF_TIMEOUT = 20
SCHRIFTGROESSEN = {"klein": 0.85, "normal": 1.0, "gross": 1.15, "sehr_gross": 1.3}
STANDARD_AKZENT = "#e0393e"

# Farben je Thema. Beim Thema „E-Ink“ werden sie auf die Displayfarben gesetzt.
FARBEN = {
    "hell": {"bg": "#ffffff", "ink": "#111418", "linie": "#c9ccd1", "rot": "#e0393e", "gruen": "#1f9d55",
             "blau": "#2f6fde", "gelb": "#f5c400", "orange": "#f08c00", "violett": "#8e44ad",
             "grau": "#8a8f98", "hellgrau": "#c9ccd1"},
    "dunkel": {"bg": "#101214", "ink": "#f3f4f6", "linie": "#3a3f46", "rot": "#ff5a5f", "gruen": "#3ccf7a",
               "blau": "#5b9bff", "gelb": "#ffd43b", "orange": "#ffa94d", "violett": "#b57edc",
               "grau": "#6b7079", "hellgrau": "#3a3f46"},
}
# Farben der Bild-Ansichten „Fenster“ und „Poesie“ außerhalb des E-Ink-Themas
KUNST_FARBEN = {
    "schwarz": "#111418", "weiss": "#ffffff", "rot": "#e0393e", "gruen": "#3a9b4a", "blau": "#2f5fd0",
    "gelb": "#f5c400", "orange": "#ef7d22", "violett": "#7b3fa0", "grau": "#8a8f98", "hellgrau": "#d3d6da",
    "rosa": "#f4a6b4", "apricot": "#f8c48d", "mint": "#a8dcae",
}

# Farbrollen, die das Template beim Thema „E-Ink“ verwendet (siehe utils/eink_farben.py)
EINK_ROLLEN = ("rot", "gruen", "blau", "gelb", "orange", "violett", "grau", "hellgrau")


class Wetter(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["style_settings"] = False
        return template_params

    def generate_image(self, settings, device_config):
        try:
            lat = float(settings.get("latitude"))
            lon = float(settings.get("longitude"))
        except (TypeError, ValueError):
            raise RuntimeError("Bitte einen Ort auswählen")

        ansicht = settings.get("ansicht") or "heute"
        if ansicht not in ANSICHTEN:
            raise RuntimeError("Ungültige Ansicht")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        tz_name = device_config.get_config("timezone", default="Europe/Berlin")
        tz = self.zeitzone(tz_name)
        jetzt = self.jetzt(tz)

        try:
            wetter = lese_open_meteo(self.vorhersage(lat, lon, tz.key), tz)
        except Exception as e:
            logger.error(f"Open-Meteo fehlgeschlagen: {e}")
            raise RuntimeError("Wetterdaten konnten nicht abgerufen werden, bitte später erneut versuchen.")
        if not wetter.tage or not wetter.stunden:
            raise RuntimeError("Der Wetterdienst hat keine Vorhersage geliefert.")

        if settings.get("warnungen", "true") != "false":
            try:
                wetter.warnungen = lese_warnungen(self.warnungen(lat, lon, tz.key), tz, jetzt)
            except Exception as e:
                logger.warning(f"DWD-Warnungen nicht verfügbar: {e}")

        thema = settings.get("thema") or "eink"
        breite, hoehe = dimensions
        if ansicht in KUNST_ANSICHTEN:
            return self.kunst_bild(ansicht, wetter, jetzt, settings, device_config, dimensions, thema)

        einfarbig = settings.get("temperaturfarbe") == "einfarbig"
        anzahl_tage = 6 if ansicht == "beides" else 7
        daten = baue_ansicht(wetter, jetzt, parse_details(settings.get("details")), einfarbig, anzahl_tage)

        farben, akzent = self.farben(thema, settings.get("akzentfarbe") or STANDARD_AKZENT, device_config)

        skala = SCHRIFTGROESSEN.get(settings.get("schriftgroesse"), 1.0)
        template_params = {
            "ansicht": ansicht,
            "daten": daten,
            "ort": (settings.get("ortName") or "").strip(),
            "thema": thema,
            "icons": "linien" if settings.get("iconstil") == "linien" else "farbig",
            "farben": farben,
            "akzent": akzent,
            "basis_px": round((breite + hoehe) / 1280 * 16 * skala, 2),
            "hochformat": hoehe > breite,
            "stand": f"{jetzt.hour}:{jetzt.minute:02d}",
            "icon": wetter_icon,
            "symbol": symbol,
            "plugin_settings": {},
        }

        image = self.render_image(dimensions, "wetter.html", "wetter.css", template_params)
        if not image:
            raise RuntimeError("Screenshot fehlgeschlagen, bitte Logs prüfen.")
        if thema == "eink":
            # Mischfarben (z. B. das wärmere Gelb) als festes Pixelmuster einsetzen
            image = muster_einsetzen(image, palette(device_config.get_config("display_type", default="")))
        return image

    def kunst_bild(self, ansicht, wetter, jetzt, settings, device_config, dimensions, thema):
        """„Fenster“ und „Poesie“: das Wetter als Bild statt als Datenanzeige."""
        pigmente = palette(device_config.get_config("display_type", default=""))
        if thema == "eink":
            farben = rollen_farben(pigmente)
        else:
            farben = dict(KUNST_FARBEN)
        breite, hoehe = dimensions
        template_params = {
            "farben": farben,
            "ort": (settings.get("ortName") or "").strip(),
            "datum": datum_text(jetzt.date()),
            "warnung": wetter.warnungen[0] if wetter.warnungen else None,
            "basis_px": round((breite + hoehe) / 1280 * 16, 2),
            "hochformat": hoehe > breite,
            "plugin_settings": {},
        }
        if ansicht == "fenster":
            template_params["szene"] = szene_fenster(wetter, jetzt)
        else:
            template_params["gedicht"] = poesie(wetter, jetzt)

        image = self.render_image(dimensions, f"wetter_{ansicht}.html", "wetter_kunst.css", template_params)
        if not image:
            raise RuntimeError("Screenshot fehlgeschlagen, bitte Logs prüfen.")
        if thema == "eink":
            image = muster_einsetzen(image, pigmente)
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
    def farben(thema, akzent, device_config):
        """CSS-Farben des Themas; bei „E-Ink“ die Farbrollen aus dem Farbtest."""
        if thema == "eink":
            pigmente = palette(device_config.get_config("display_type", default=""))
            rollen = rollen_farben(pigmente)
            farben = {rolle: rollen[rolle] for rolle in EINK_ROLLEN}
            farben.update({"bg": pigmente["weiss"], "ink": pigmente["schwarz"], "linie": pigmente["schwarz"]})
            buntes = [f for name, f in pigmente.items() if name != "weiss"]
            return farben, naechste_farbe(akzent, buntes)
        return FARBEN.get(thema, FARBEN["hell"]), akzent

    @staticmethod
    def vorhersage(lat, lon, tz_name):
        params = {
            "latitude": lat,
            "longitude": lon,
            "timezone": tz_name,
            "forecast_days": 8,
            "wind_speed_unit": "kmh",
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,is_day,weather_code,"
                       "wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation,cloud_cover",
            "hourly": "temperature_2m,precipitation,precipitation_probability,weather_code,is_day,uv_index",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
                     "precipitation_probability_max,sunrise,sunset,uv_index_max",
        }
        response = requests.get(OPEN_METEO_URL, params=params, timeout=ABRUF_TIMEOUT,
                                headers={"User-Agent": "InkyPi"})
        response.raise_for_status()
        return response.json()

    @staticmethod
    def warnungen(lat, lon, tz_name):
        response = requests.get(BRIGHT_SKY_ALERTS_URL, params={"lat": lat, "lon": lon, "tz": tz_name},
                                timeout=ABRUF_TIMEOUT, headers={"User-Agent": "InkyPi"})
        response.raise_for_status()
        return response.json()
