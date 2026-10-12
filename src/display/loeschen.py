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
# Ab diesem Anteil der Fläche (Prozent), der sich seit dem letzten Löschen verändert hat,
# wird gelöscht; anpassbar über den Löschtest (Einstellung „display_clear_threshold“)
STANDARD_SCHWELLE = 30
MIN_SCHWELLE, MAX_SCHWELLE = 5, 100
# Spätestens nach so vielen Bildern ohne Löschen wird gelöscht, weil sich Reste
# auch an denselben Stellen stapeln (z. B. Uhr jede Minute; „display_clear_max_updates“)
STANDARD_MAX_BILDER = 20
MIN_MAX_BILDER, MAX_MAX_BILDER = 1, 500

# Vergleichsgröße und Farben, mit denen der Waveshare-Treiber die Pigmente anspricht
VERGLEICH_BREITE = 160
PIGMENTE = ((0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 128, 0))


def modus(device_config):
    value = device_config.get_config("display_clear_mode", default=STANDARD_MODUS)
    return value if value in MODI else STANDARD_MODUS


def _ganzzahl(device_config, key, standard, grenzen):
    try:
        value = int(device_config.get_config(key, default=standard))
    except (TypeError, ValueError):
        return standard
    return max(grenzen[0], min(grenzen[1], value))


def schwelle(device_config):
    """Schwelle in Prozent der Fläche für „automatisch“."""
    return _ganzzahl(device_config, "display_clear_threshold", STANDARD_SCHWELLE, (MIN_SCHWELLE, MAX_SCHWELLE))


def max_bilder(device_config):
    """Höchstens so viele Bilder hintereinander ohne Löschen."""
    return _ganzzahl(device_config, "display_clear_max_updates", STANDARD_MAX_BILDER, (MIN_MAX_BILDER, MAX_MAX_BILDER))


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


class Verlauf:
    """Was seit dem letzten Löschen auf dem Display passiert ist.

    Reste entstehen nicht nur bei einem großen Wechsel, sie sammeln sich auch über
    viele kleine Wechsel an. Deshalb zählt der Verlauf die Bilder seit dem Löschen
    und merkt sich jede Stelle, die sich seitdem mindestens einmal geändert hat.
    """

    def __init__(self):
        self.letztes = None   # zuletzt angezeigtes Bild (pigment_bild)
        self.maske = None     # 1 = Stelle hat sich seit dem Löschen geändert
        self.bilder = 0       # Bilder seit dem Löschen (ohne das gelöschte selbst)

    def flaeche_nach(self, nachher):
        """Anteil der Fläche (0–1), der sich seit dem Löschen geändert hätte, käme `nachher` ohne Löschen."""
        if self.letztes is None or self.letztes.size != nachher.size:
            return 1.0
        a, b = self.letztes.tobytes(), nachher.tobytes()
        maske = self.maske or bytes(len(a))
        geaendert = sum(1 for m, x, y in zip(maske, a, b) if m or x != y)
        return geaendert / max(1, len(a))

    def merken(self, nachher, geloescht):
        """Nach dem Anzeigen: neues Bild übernehmen."""
        if geloescht or self.letztes is None or self.letztes.size != nachher.size:
            self.maske = bytes(len(nachher.tobytes()))
            self.bilder = 0
        else:
            a, b = self.letztes.tobytes(), nachher.tobytes()
            self.maske = bytes(1 if m or x != y else 0 for m, x, y in zip(self.maske, a, b))
            self.bilder += 1
        self.letztes = nachher


def entscheiden(modus, verlauf, nachher, letztes_loeschen, jetzt=None,
                schwelle=STANDARD_SCHWELLE, max_bilder=STANDARD_MAX_BILDER):
    """Ob gelöscht wird, und warum (für die Statusanzeige).

    Automatisch wird gelöscht, wenn
      - das vorige Bild unbekannt ist (nach einem Neustart),
      - seit dem letzten Löschen mehr als 24 Stunden vergangen sind,
      - schon `max_bilder` Bilder ohne Löschen kamen (Reste stapeln sich), oder
      - sich seit dem letzten Löschen insgesamt mindestens `schwelle` Prozent der Fläche
        geändert haben (z. B. Wechsel zu einer anderen Ansicht).

    Args:
        verlauf: ``Verlauf`` des Displays.
        nachher: ``pigment_bild`` des neuen Bilds.
        letztes_loeschen: Zeitpunkt (time.time()) des letzten Löschens oder None.
    """
    if modus == "immer":
        return True, None
    if modus == "nie":
        return False, None
    jetzt = time.time() if jetzt is None else jetzt
    if verlauf.letztes is None:
        return True, "erstes Bild seit dem Start"
    if letztes_loeschen is None or jetzt - letztes_loeschen >= MAX_SEKUNDEN_OHNE_LOESCHEN:
        return True, "tägliche Auffrischung"
    if verlauf.bilder >= max_bilder:
        return True, f"{verlauf.bilder} Bilder ohne Löschen"
    flaeche = round(verlauf.flaeche_nach(nachher) * 100)
    if flaeche >= schwelle:
        return True, f"{flaeche} % der Fläche verändert"
    return False, f"{flaeche} % der Fläche verändert, Bild {verlauf.bilder + 1} ohne Löschen"
