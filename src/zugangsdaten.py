"""Zugangsdaten (API-Schlüssel, Passwörter) für Plugins.

Die Werte liegen wie bisher in der .env im InkyPi-Ordner und werden von den
Plugins per `device_config.load_env_key(...)` gelesen. Über die Weboberfläche
lassen sie sich setzen und löschen, aber nie wieder auslesen – angezeigt wird
nur, ob ein Wert hinterlegt ist.

Nur Standardbibliothek, damit Katalog und Prüfungen ohne Abhängigkeiten
testbar sind.
"""

import re

# Bekannte Schlüssel, nach Plugin gruppiert. "geheim": Eingabe als Passwortfeld.
KATALOG = [
    {
        "gruppe": "iCloud-Kalender",
        "hinweis": "Nur nötig, wenn private Kalender direkt aus dem iCloud-Konto geladen werden. "
                   "Öffentliche Kalender-Links brauchen keine Zugangsdaten.",
        "schluessel": [
            {"key": "ICLOUD_APPLE_ID", "name": "Apple-ID", "geheim": False,
             "hilfe": "Die E-Mail-Adresse deiner Apple-ID."},
            {"key": "ICLOUD_APP_PASSWORT", "name": "App-spezifisches Passwort", "geheim": True,
             "hilfe": "Nicht dein normales Apple-Passwort! Erstellen unter account.apple.com → "
                      "Anmeldung und Sicherheit → App-spezifische Passwörter.",
             "link": "https://account.apple.com"},
        ],
    },
    {
        "gruppe": "Wetter & Tagesdashboard",
        "schluessel": [
            {"key": "OPEN_WEATHER_MAP_SECRET", "name": "OpenWeatherMap-API-Schlüssel", "geheim": True,
             "hilfe": "Aus deinem Konto bei OpenWeatherMap (One Call API 3.0).",
             "link": "https://home.openweathermap.org/api_keys"},
        ],
    },
    {
        "gruppe": "KI-Bild & KI-Text",
        "schluessel": [
            {"key": "OPEN_AI_SECRET", "name": "OpenAI-API-Schlüssel", "geheim": True,
             "hilfe": "Im OpenAI-Entwicklerportal unter „API keys“.",
             "link": "https://platform.openai.com/api-keys"},
        ],
    },
    {
        "gruppe": "NASA-Astronomiebild des Tages",
        "schluessel": [
            {"key": "NASA_SECRET", "name": "NASA-API-Schlüssel", "geheim": True,
             "hilfe": "Kostenlos auf api.nasa.gov anfordern.", "link": "https://api.nasa.gov/"},
        ],
    },
    {
        "gruppe": "Unsplash",
        "schluessel": [
            {"key": "UNSPLASH_ACCESS_KEY", "name": "Unsplash-Access-Key", "geheim": True,
             "hilfe": "Aus einer App im Unsplash-Entwicklerbereich.",
             "link": "https://unsplash.com/oauth/applications"},
        ],
    },
    {
        "gruppe": "GitHub",
        "schluessel": [
            {"key": "GITHUB_SECRET", "name": "GitHub-Token", "geheim": True,
             "hilfe": "Ein Personal Access Token (nur Lesezugriff nötig).",
             "link": "https://github.com/settings/tokens"},
        ],
    },
    {
        "gruppe": "Bildalbum",
        "schluessel": [
            {"key": "IMMICH_KEY", "name": "Immich-API-Schlüssel", "geheim": True,
             "hilfe": "In Immich unter Kontoeinstellungen → API-Schlüssel."},
        ],
    },
]

BEKANNTE = {s["key"] for g in KATALOG for s in g["schluessel"]}
_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
MAX_LAENGE = 4096


def pruefe(key, wert):
    """Gibt eine Fehlermeldung zurück oder None, wenn Name und Wert in Ordnung sind."""
    if not isinstance(key, str) or not _NAME.match(key):
        return "Ungültiger Name (erlaubt: Großbuchstaben, Ziffern und _)"
    if not isinstance(wert, str):
        return "Ungültiger Wert"
    if len(wert) > MAX_LAENGE:
        return "Der Wert ist zu lang"
    if any(c in wert for c in "\r\n\0"):
        return "Der Wert darf keine Zeilenumbrüche enthalten"
    return None


def katalog_mit_status(gesetzt):
    """Katalog plus Status je Schlüssel; unbekannte, aber gesetzte Schlüssel unter „Weitere“."""
    gruppen = []
    for gruppe in KATALOG:
        gruppen.append({**gruppe, "schluessel": [
            {**s, "gesetzt": s["key"] in gesetzt} for s in gruppe["schluessel"]
        ]})
    weitere = sorted(k for k in gesetzt if k not in BEKANNTE)
    if weitere:
        gruppen.append({
            "gruppe": "Weitere",
            "hinweis": "Diese Einträge stehen in der .env, gehören aber zu keinem bekannten Plugin.",
            "schluessel": [{"key": k, "name": k, "geheim": True, "hilfe": "", "gesetzt": True} for k in weitere],
        })
    return gruppen
