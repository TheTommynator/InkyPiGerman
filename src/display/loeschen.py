"""Wann das Display vor einem neuen Bild gelöscht wird.

Das Löschen (alles einmal weiß aufbauen) entfernt Geisterbilder, also schwache
Reste des vorigen Bilds. Es kostet aber einen kompletten zweiten Bildaufbau und
damit etwa die Hälfte der Zeit. Drei Einstellungen:

  - „immer“: vor jedem Bild löschen (bisheriges Verhalten)
  - „nie“: nie löschen – am schnellsten, auf Dauer können Reste bleiben
  - „automatisch“: nur wenn es sich lohnt, siehe ``entscheiden``
"""

import time

from PIL import Image

MODI = ("immer", "automatisch", "nie")
STANDARD_MODUS = "immer"

# Spätestens nach dieser Zeit wird wieder gelöscht, damit sich keine Reste ansammeln
MAX_SEKUNDEN_OHNE_LOESCHEN = 24 * 60 * 60
# Ab diesem Anteil geänderter Bildpunkte gilt ein Wechsel als groß
ANTEIL_GROSSER_WECHSEL = 0.3

# Vergleichsgröße und Farben, mit denen der Waveshare-Treiber die Pigmente anspricht
VERGLEICH_BREITE = 160
PIGMENTE = ((0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 128, 0))


def modus(device_config):
    value = device_config.get_config("display_clear_mode", default=STANDARD_MODUS)
    return value if value in MODI else STANDARD_MODUS


def pigment_bild(image):
    """Verkleinertes Bild, auf die sieben Pigmente gerundet (ohne Raster), für den Vergleich."""
    image = image.convert("RGB")
    hoehe = max(1, round(image.height * VERGLEICH_BREITE / max(1, image.width)))
    klein = image.resize((VERGLEICH_BREITE, hoehe), Image.Resampling.BILINEAR)
    palette = Image.new("P", (1, 1))
    palette.putpalette([wert for farbe in PIGMENTE for wert in farbe])
    return klein.quantize(palette=palette, dither=Image.Dither.NONE)


def anteil_geaendert(vorher, nachher):
    """Anteil der Bildpunkte (0–1), deren Pigment sich ändert."""
    if vorher.size != nachher.size:
        return 1.0
    a, b = vorher.tobytes(), nachher.tobytes()
    return sum(1 for x, y in zip(a, b) if x != y) / max(1, len(a))


def entscheiden(modus, vorher, nachher, letztes_loeschen, jetzt=None):
    """Ob gelöscht wird, und warum (für die Statusanzeige).

    Automatisch wird gelöscht, wenn
      - das vorige Bild unbekannt ist (nach einem Neustart),
      - seit dem letzten Löschen mehr als 24 Stunden vergangen sind, oder
      - sich mindestens 30 % der Bildpunkte ändern (z. B. Wechsel zu einer anderen Ansicht).
    Kleine Änderungen wie eine neue Uhrzeit oder ein aktualisierter Wert brauchen kein Löschen.

    Args:
        vorher, nachher: Ergebnisse von ``pigment_bild`` (vorher darf None sein).
        letztes_loeschen: Zeitpunkt (time.time()) des letzten Löschens oder None.
    """
    if modus == "immer":
        return True, None
    if modus == "nie":
        return False, None
    jetzt = time.time() if jetzt is None else jetzt
    if vorher is None:
        return True, "erstes Bild seit dem Start"
    if letztes_loeschen is None or jetzt - letztes_loeschen >= MAX_SEKUNDEN_OHNE_LOESCHEN:
        return True, "tägliche Auffrischung"
    anteil = anteil_geaendert(vorher, nachher)
    if anteil >= ANTEIL_GROSSER_WECHSEL:
        return True, f"großer Bildwechsel ({round(anteil * 100)} %)"
    return False, f"nur {round(anteil * 100)} % geändert"
