from plugins.base_plugin.base_plugin import BasePlugin
import logging

logger = logging.getLogger(__name__)


class HelloWorld(BasePlugin):
    def generate_settings_template(self):
        """
        Aktiviert zusätzlich die globalen Style-Settings
        (Hintergrund, Rahmen, Margin etc.)
        """
        template_params = super().generate_settings_template()
        template_params["style_settings"] = True
        return template_params

    def generate_image(self, settings, device_config):
        # -----------------------------
        # Überschrift
        # -----------------------------
        title = (settings.get("title") or "").strip()
        title_color = settings.get("title_color", "#000000")

        try:
            title_size = int(settings.get("title_size", 96))
        except ValueError:
            raise RuntimeError("Überschrift-Größe muss eine Zahl sein.")

        title_size = max(20, min(title_size, 200))

        # -----------------------------
        # Text (mehrzeilig)
        # -----------------------------
        raw_text = (settings.get("text") or "").strip()
        if not raw_text and not title:
            raw_text = "Hello World 👋"

        # Zeilenumbrüche aus <textarea> für HTML vorbereiten
        text_html = raw_text.replace("\n", "<br>")

        text_color = settings.get("text_color", "#000000")

        try:
            font_size = int(settings.get("font_size", 48))
        except ValueError:
            raise RuntimeError("Textgröße muss eine Zahl sein.")

        font_size = max(12, min(font_size, 160))

        # -----------------------------
        # Auto-Fit
        # -----------------------------
        auto_fit_raw = settings.get("auto_fit", False)
        auto_fit = (
            auto_fit_raw is True
            or str(auto_fit_raw).lower() == "true"
        )

        # -----------------------------
        # Template-Parameter
        # -----------------------------
        template_params = {
            # Überschrift
            "title": title,
            "title_color": title_color,
            "title_size": title_size,

            # Text
            "text": text_html,
            "text_color": text_color,
            "font_size": font_size,

            # Verhalten
            "auto_fit": auto_fit,

            # Wichtig für plugin.html (Style Settings)
            "plugin_settings": settings,
        }

        # -----------------------------
        # Display-Auflösung
        # -----------------------------
        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        # -----------------------------
        # Rendern
        # -----------------------------
        try:
            image = self.render_image(
                dimensions,
                "helloworld.html",
                "helloworld.css",
                template_params
            )
        except Exception as e:
            logger.exception("Fehler beim Rendern des HelloWorld-Plugins")
            raise RuntimeError(f"Rendering-Fehler: {e}")

        if image is None:
            raise RuntimeError(
                "Rendering fehlgeschlagen (kein Bild erzeugt). Bitte Logs prüfen."
            )

        return image