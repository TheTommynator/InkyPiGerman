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
# Bis zu drei iCloud-Konten, z. B. für mehrere Personen im Haushalt. Konto 1
# nutzt die bisherigen Namen ohne Nummer, damit bestehende .env-Dateien passen.
ICLOUD_KONTEN = 3


def icloud_schluessel(nr):
    """.env-Namen für iCloud-Konto `nr` (1, 2, 3)."""
    s = "" if nr == 1 else f"_{nr}"
    return {"name": f"ICLOUD_KONTO_NAME{s}", "apple_id": f"ICLOUD_APPLE_ID{s}",
            "passwort": f"ICLOUD_APP_PASSWORT{s}"}


def icloud_konten(lade):
    """Alle iCloud-Konten mit Apple-ID und Passwort. `lade(key)` liest einen .env-Wert."""
    konten = []
    for nr in range(1, ICLOUD_KONTEN + 1):
        k = icloud_schluessel(nr)
        apple_id, passwort = (lade(k["apple_id"]) or "").strip(), (lade(k["passwort"]) or "").strip()
        if apple_id and passwort:
            name = (lade(k["name"]) or "").strip() or f"iCloud-Konto {nr}"
            konten.append({"nr": nr, "name": name, "apple_id": apple_id, "passwort": passwort})
    return konten


def _icloud_gruppe(nr):
    k = icloud_schluessel(nr)
    if nr == 1:
        hinweis = ("Nur nötig, wenn private Kalender direkt aus dem iCloud-Konto geladen werden. "
                   "Öffentliche Kalender-Links brauchen keine Zugangsdaten.")
    else:
        hinweis = ("Optional: ein weiteres iCloud-Konto, z. B. das einer anderen Person im Haushalt. "
                   "Seine Kalender erscheinen dann zusätzlich im iCloud-Kalender.")
    return {
        "gruppe": f"iCloud-Konto {nr}",
        "icloud_konto": nr,
        "hinweis": hinweis,
        "schluessel": [
            {"key": k["name"], "name": "Name des Kontos (optional)", "geheim": False,
             "hilfe": "Erscheint in den Kalender-Einstellungen, z. B. „Max“. "
                      "Hilft, wenn mehrere Konten gleich benannte Kalender haben."},
            {"key": k["apple_id"], "name": "Apple-ID", "geheim": False,
             "hilfe": "Die E-Mail-Adresse der Apple-ID."},
            {"key": k["passwort"], "name": "App-spezifisches Passwort", "geheim": True,
             "hilfe": "Nicht das normale Apple-Passwort! Erstellen unter account.apple.com → "
                      "Anmeldung und Sicherheit → App-spezifische Passwörter.",
             "link": "https://account.apple.com"},
        ],
    }


# Bekannte Schlüssel, nach Plugin gruppiert. "geheim": Eingabe als Passwortfeld.
KATALOG = [_icloud_gruppe(nr) for nr in range(1, ICLOUD_KONTEN + 1)] + [
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
