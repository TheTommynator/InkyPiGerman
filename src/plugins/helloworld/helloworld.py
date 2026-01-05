from plugins.base_plugin.base_plugin import BasePlugin
import logging

logger = logging.getLogger(__name__)

class HelloWorld(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        # Damit im Web-UI die "Style Settings" (Rahmen, Margin, Hintergrund etc.) auftauchen:
        template_params["style_settings"] = True
        return template_params

    def generate_image(self, settings, device_config):
        # --- Settings lesen (mit Defaults) ---
        text = (settings.get("text") or "").strip()
        if not text:
            text = "Hello World 👋"

        font_family = settings.get("font_family", "Inter")
        try:
            font_size = int(settings.get("font_size", 48))
        except ValueError:
            raise RuntimeError("Schriftgröße muss eine Zahl sein.")

        # simple bounds, damit es nicht komplett eskaliert
        font_size = max(10, min(font_size, 200))

        text_color = settings.get("text_color", "#000000")
        align = settings.get("align", "center")

        template_params = {
            "text": text,
            "font_family": font_family,
            "font_size": font_size,
            "text_color": text_color,
            "align": align,

            # Wichtig: damit plugin.html die globalen Style-Settings anwenden kann
            "plugin_settings": settings,
        }

        # Auflösung / Rotation berücksichtigen
        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        image = self.render_image(
            dimensions=dimensions,
            html_file="helloworld.html",
            css_file="helloworld.css",
            template_params=template_params
        )

        if not image:
            raise RuntimeError("Rendering fehlgeschlagen. Bitte Logs prüfen.")
        return image