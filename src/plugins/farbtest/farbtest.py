"""Farbtest: Testtafeln für 7-Farben-E-Ink-Displays.

Tafel „Grundfarben“ zeigt die Pigmente als große Flächen und in kleinen
Größen (Linien, Schrift, Symbole) – so sieht man, ab wann eine Farbe kippt,
z. B. kleines Blau, das fast schwarz wirkt.

Tafel „Mischungen“ zeigt nummerierte Musterflächen aus zwei Pigmenten
(siehe utils/eink_farben.py). Die Nummern dienen als Rückmeldung, welche
Variante auf dem eigenen Display am besten wirkt.
"""

from plugins.base_plugin.base_plugin import BasePlugin
from utils.eink_farben import PIGMENT_NAMEN, css_flaeche, palette, titel

TAFELN = ("grundfarben", "mischungen")

GRUNDFARBEN = ("schwarz", "rot", "gruen", "blau", "gelb", "orange")
BUNTE_FARBEN = ("rot", "gruen", "blau", "gelb", "orange")

# Reihen der Mischungstafel: jeweils mit der reinen Farbe als Vergleich
MISCHUNGS_REIHEN = (
    ("blau", "blau_weiss_75", "blau_weiss_50", "blau_weiss_25", "blau_gruen_75", "blau_gruen_50"),
    ("gelb", "gelb_orange_75", "gelb_orange_50", "gelb_gruen_75", "gelb_weiss_75", "orange"),
    ("rot", "rot_orange_50", "rot_weiss_50", "rot_blau_50", "orange_weiss_50", "gruen"),
    ("gruen_gelb_50", "gruen_weiss_50", "gruen_blau_75", "schwarz_weiss_50", "schwarz_weiss_25", "schwarz"),
)


def mischungs_kacheln(farben):
    """Alle Kacheln der Mischungstafel, fortlaufend nummeriert."""
    kacheln = []
    for reihe in MISCHUNGS_REIHEN:
        for name in reihe:
            rein = name in PIGMENT_NAMEN
            kacheln.append({
                "nummer": len(kacheln) + 1,
                "name": name,
                "titel": f"{titel(name)} (rein)" if rein else titel(name),
                "rein": rein,
                "flaeche": css_flaeche(name, farben),
            })
    return kacheln


class Farbtest(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["style_settings"] = False
        return template_params

    def generate_image(self, settings, device_config):
        tafel = settings.get("tafel") or "grundfarben"
        if tafel not in TAFELN:
            raise RuntimeError("Ungültige Tafel")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        display_type = device_config.get_config("display_type", default="")
        farben = palette(display_type)
        breite, hoehe = dimensions
        template_params = {
            "tafel": tafel,
            "farben": farben,
            "palette_name": "Inky" if str(display_type).startswith("inky") else "Waveshare",
            "grundfarben": [{"name": n, "titel": PIGMENT_NAMEN[n], "farbe": farben[n]} for n in GRUNDFARBEN],
            "bunte": [{"name": n, "titel": PIGMENT_NAMEN[n], "farbe": farben[n]} for n in BUNTE_FARBEN],
            "kacheln": mischungs_kacheln(farben),
            "hochformat": hoehe > breite,
            "basis_px": round((breite + hoehe) / 1280 * 16, 2),
            "plugin_settings": {},
        }

        image = self.render_image(dimensions, "farbtest.html", "farbtest.css", template_params)
        if not image:
            raise RuntimeError("Screenshot fehlgeschlagen, bitte Logs prüfen.")
        return image
