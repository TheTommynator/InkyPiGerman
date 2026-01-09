from plugins.base_plugin.base_plugin import BasePlugin
import logging
import requests
from datetime import datetime, timezone
import pytz
import xml.etree.ElementTree as ET
from html import unescape

logger = logging.getLogger(__name__)

# --- Lokalisierte (DE) Datumsdarstellung (deterministisch, ohne locale) ---
WEEKDAYS_FULL_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONTHS_FULL_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni",
                  "Juli", "August", "September", "Oktober", "November", "Dezember"]

def format_date_de(dt: datetime) -> str:
    wd = WEEKDAYS_FULL_DE[dt.weekday()]
    month = MONTHS_FULL_DE[dt.month - 1]
    return f"{wd}, {dt.day:02d}. {month} {dt.year}"

# --- OpenWeatherMap OneCall 3.0 ---
OWM_ONECALL_URL = (
    "https://api.openweathermap.org/data/3.0/onecall"
    "?lat={lat}&lon={lon}&units={units}&exclude=minutely,hourly,alerts&appid={api_key}&lang=de"
)

UNITS = {
    "metric": {"temp": "°C"},
    "imperial": {"temp": "°F"},
    "standard": {"temp": "K"},
}

class DailyDashboard(BasePlugin):
    """
    Tagesdashboard:
    - Datum (deutsch)
    - Wetter via OpenWeatherMap (Temp + Description + Min/Max heute)
    - RSS Headlines (2-3)
    """

    # einfacher In-Memory Cache (Service-Lifetime)
    _cache = {
        "weather": {"ts": 0, "data": None},
        "rss": {"ts": 0, "data": None},
    }

    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["api_key"] = {
            "required": True,
            "service": "OpenWeatherMap",
            "expected_key": "OPEN_WEATHER_MAP_SECRET"
        }
        template_params["style_settings"] = True
        return template_params

    def generate_image(self, settings, device_config):
        # --- Settings lesen ---
        try:
            lat = float(settings.get("latitude"))
            lon = float(settings.get("longitude"))
        except Exception:
            raise RuntimeError("Bitte Breitengrad und Längengrad korrekt angeben.")

        units = settings.get("units", "metric")
        if units not in ["metric", "imperial", "standard"]:
            raise RuntimeError("Einheiten sind ungültig.")

        rss_url = (settings.get("rss_url") or "").strip()
        if not rss_url:
            raise RuntimeError("Bitte eine RSS-URL angeben.")

        try:
            rss_count = int(settings.get("rss_count", 3))
        except Exception:
            rss_count = 3
        rss_count = max(1, min(rss_count, 5))

        # Cache TTLs
        weather_ttl_min = self._safe_int(settings.get("weather_cache_minutes", 15), 15, 1, 120)
        rss_ttl_min = self._safe_int(settings.get("rss_cache_minutes", 30), 30, 1, 240)

        # Farben / Layout
        accent = settings.get("accent_color", "#0000FF")      # Blau default
        panel_bg = settings.get("panel_bg", "none")           # optional Hintergrund
        frame = settings.get("frame", "none")                 # none | thin | thick
        frame_color = settings.get("frame_color", "#000000")  # schwarz default

        # Typo
        title_font = settings.get("title_font", "Inter")
        body_font = settings.get("body_font", "Inter")
        title_size = self._safe_int(settings.get("title_size", 56), 56, 20, 120)
        body_size = self._safe_int(settings.get("body_size", 28), 28, 14, 60)

        # timezone
        tz_name = device_config.get_config("timezone", default="Europe/Berlin")
        try:
            tz = pytz.timezone(tz_name)
        except Exception:
            tz = pytz.timezone("Europe/Berlin")

        now = datetime.now(tz)

        # --- API Key ---
        api_key = device_config.load_env_key("OPEN_WEATHER_MAP_SECRET")
        if not api_key:
            raise RuntimeError("OpenWeatherMap-API-Key ist nicht konfiguriert.")

        # --- Daten holen (mit Cache) ---
        weather = self._get_weather_cached(api_key, lat, lon, units, weather_ttl_min)
        news_items = self._get_rss_cached(rss_url, rss_count, rss_ttl_min)

        # --- Wetter Daten extrahieren ---
        current = (weather or {}).get("current", {}) if isinstance(weather, dict) else {}
        daily0 = ((weather or {}).get("daily") or [{}])[0] if isinstance(weather, dict) else {}

        temp = current.get("temp")
        desc = ""
        try:
            desc = (current.get("weather") or [{}])[0].get("description") or ""
        except Exception:
            desc = ""

        tmin = None
        tmax = None
        try:
            tmin = (daily0.get("temp") or {}).get("min")
            tmax = (daily0.get("temp") or {}).get("max")
        except Exception:
            pass

        # Safe rounding
        temp_str = self._fmt_num(temp)
        tmin_str = self._fmt_num(tmin)
        tmax_str = self._fmt_num(tmax)

        template_params = {
            "date_de": format_date_de(now),
            "temp": temp_str,
            "temp_unit": UNITS.get(units, UNITS["metric"])["temp"],
            "desc": desc,
            "tmin": tmin_str,
            "tmax": tmax_str,
            "news": news_items,

            # styling
            "accent": accent,
            "panel_bg": panel_bg,
            "frame": frame,
            "frame_color": frame_color,
            "title_font": title_font,
            "body_font": body_font,
            "title_size": title_size,
            "body_size": body_size,

            "plugin_settings": settings,
        }

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        image = self.render_image(dimensions, "daily_dashboard.html", "daily_dashboard.css", template_params)
        if image is None:
            raise RuntimeError("Rendering fehlgeschlagen. Bitte Logs prüfen.")
        return image

    # ----------------------------
    # Helpers
    # ----------------------------
    def _safe_int(self, value, default, lo, hi):
        try:
            n = int(value)
        except Exception:
            n = default
        return max(lo, min(n, hi))

    def _fmt_num(self, v):
        if v is None:
            return "k. A."
        try:
            return str(int(round(float(v), 0)))
        except Exception:
            return "k. A."

    def _get_weather_cached(self, api_key, lat, lon, units, ttl_minutes):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        cached = self._cache["weather"]
        if cached["data"] is not None and (now_ts - cached["ts"]) < ttl_minutes * 60:
            return cached["data"]

        url = OWM_ONECALL_URL.format(lat=lat, lon=lon, units=units, api_key=api_key)
        try:
            r = requests.get(url, timeout=12)
            if not (200 <= r.status_code < 300):
                logger.error(f"OWM weather failed: {r.status_code} {r.text[:200]}")
                raise RuntimeError("Wetterdaten konnten nicht abgerufen werden.")
            data = r.json()
        except RuntimeError:
            raise
        except Exception as e:
            logger.exception("OWM request error")
            raise RuntimeError("Wetterdaten konnten nicht abgerufen werden.") from e

        self._cache["weather"] = {"ts": now_ts, "data": data}
        return data

    def _get_rss_cached(self, rss_url, count, ttl_minutes):
        now_ts = int(datetime.now(timezone.utc).timestamp())
        cached = self._cache["rss"]
        cache_key = f"{rss_url}|{count}"
        if cached["data"] is not None and cached.get("key") == cache_key and (now_ts - cached["ts"]) < ttl_minutes * 60:
            return cached["data"]

        items = self._fetch_rss_items(rss_url, count)
        self._cache["rss"] = {"ts": now_ts, "data": items, "key": cache_key}
        return items

    def _fetch_rss_items(self, rss_url, count):
        """
        Minimaler RSS/Atom Parser ohne Zusatz-Abhängigkeit.
        Unterstützt typische RSS 2.0 <item><title>, Atom <entry><title>.
        """
        try:
            r = requests.get(rss_url, timeout=12, headers={"User-Agent": "InkyPi-DailyDashboard/1.0"})
            if not (200 <= r.status_code < 300):
                logger.error(f"RSS fetch failed: {r.status_code} {r.text[:200]}")
                raise RuntimeError("RSS konnte nicht abgerufen werden.")
            xml_text = r.text
        except RuntimeError:
            raise
        except Exception as e:
            logger.exception("RSS request error")
            raise RuntimeError("RSS konnte nicht abgerufen werden.") from e

        try:
            root = ET.fromstring(xml_text)
        except Exception as e:
            logger.exception("RSS parse error")
            raise RuntimeError("RSS konnte nicht verarbeitet werden.") from e

        titles = []

        # RSS 2.0: channel/item/title
        for item in root.findall(".//channel/item/title"):
            if item.text:
                titles.append(self._clean_text(item.text))

        # Atom: entry/title (namespace tolerant)
        if not titles:
            for entry_title in root.findall(".//{*}entry/{*}title"):
                if entry_title.text:
                    titles.append(self._clean_text(entry_title.text))

        # Fallback: any title nodes, but skip channel title if possible
        if not titles:
            for t in root.findall(".//{*}title"):
                if t.text:
                    titles.append(self._clean_text(t.text))

        # dedupe & limit
        out = []
        seen = set()
        for t in titles:
            if not t:
                continue
            if t in seen:
                continue
            seen.add(t)
            out.append(t)
            if len(out) >= count:
                break

        if not out:
            out = ["(Keine News gefunden)"]
        return out

    def _clean_text(self, s: str) -> str:
        s = unescape(s).strip()
        # very small cleanup
        s = " ".join(s.split())
        return s