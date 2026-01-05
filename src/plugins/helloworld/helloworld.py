from plugins.base_plugin.base_plugin import BasePlugin
import logging

logger = logging.getLogger(__name__)

ACEP_COLORS = {
    "black": "#000000",
    "white": "#FFFFFF",
    "red": "#FF0000",
    "yellow": "#FFFF00",
    "blue": "#0000FF",
    "green": "#00FF00",
    "orange": "#FFA500",
}

# Presets: Erzwingen Look (Rahmen/Hintergrund/Farben/Layout/Fonts/Größen)
PRESETS = {
    "hint": {
        "title_default": "Hinweis",
        "layout": "infoboard",
        "panel_bg": ACEP_COLORS["yellow"],
        "frame": "thick",
        "frame_color": ACEP_COLORS["black"],

        "title_font": "Inter",
        "title_align": "center",
        "title_color": ACEP_COLORS["black"],
        "title_size": 96,

        "text_font": "Inter",
        "text_align": "center",
        "text_color": ACEP_COLORS["black"],
        "font_size": 56,
        "min_font_size": 18,
        "auto_fit": True,
    },
    "alarm": {
        "title_default": "ALARM",
        "layout": "infoboard",
        "panel_bg": ACEP_COLORS["red"],
        "frame": "thick",
        "frame_color": ACEP_COLORS["black"],

        "title_font": "Inter",
        "title_align": "center",
        "title_color": ACEP_COLORS["white"],
        "title_size": 110,

        "text_font": "Inter",
        "text_align": "center",
        "text_color": ACEP_COLORS["white"],
        "font_size": 56,
        "min_font_size": 18,
        "auto_fit": True,
    },
    "info": {
        "title_default": "Info",
        "layout": "infoboard",
        "panel_bg": ACEP_COLORS["blue"],
        "frame": "thin",
        "frame_color": ACEP_COLORS["white"],

        "title_font": "Inter",
        "title_align": "center",
        "title_color": ACEP_COLORS["white"],
        "title_size": 92,

        "text_font": "Inter",
        "text_align": "center",
        "text_color": ACEP_COLORS["white"],
        "font_size": 52,
        "min_font_size": 18,
        "auto_fit": True,
    },
}

def _as_bool(value, default=False) -> bool:
    if value is None:
        return default
    if value is True or value is False:
        return value
    return str(value).lower() == "true"

def _as_int(value, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except Exception:
        n = default
    return max(lo, min(n, hi))


class HelloWorld(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["style_settings"] = True
        return template_params

    def generate_image(self, settings, device_config):
        # -----------------------------
        # Preset (erzwingt Look)
        # -----------------------------
        preset_key = settings.get("preset", "custom")
        preset = PRESETS.get(preset_key) if preset_key and preset_key != "custom" else None

        # Inhalt: immer editierbar
        title = (settings.get("title") or "").strip()
        text = (settings.get("text") or "").rstrip()

        if not title and preset:
            # Wenn kein Titel gesetzt, nimm Preset-Titel
            title = preset.get("title_default", "")

        if not text and not title:
            text = "Hello World 👋"

        # Styles: bei Preset aktiv -> Preset gewinnt, sonst Settings/Defaults
        def style(key, fallback):
            if preset and key in preset:
                return preset[key]
            return settings.get(key, fallback)

        layout = style("layout", "center")              # "center" | "infoboard"
        panel_bg = style("panel_bg", "none")            # "none" oder #RRGGBB
        frame = style("frame", "none")                  # "none" | "thin" | "thick"
        frame_color = style("frame_color", "#000000")

        title_font = style("title_font", "Inter")
        title_align = style("title_align", "center")
        title_color = style("title_color", "#000000")
        title_size = _as_int(style("title_size", 96), 96, 20, 200)

        text_font = style("text_font", "Inter")
        text_align = style("text_align", "center")
        text_color = style("text_color", "#000000")
        font_size = _as_int(style("font_size", 56), 56, 12, 160)
        min_font_size = _as_int(style("min_font_size", 18), 18, 10, 120)
        min_font_size = min(min_font_size, font_size)
        auto_fit = _as_bool(style("auto_fit", True), True)

        template_params = {
            "layout": layout,
            "panel_bg": panel_bg,
            "frame": frame,
            "frame_color": frame_color,

            "title": title,
            "title_font": title_font,
            "title_align": title_align,
            "title_color": title_color,
            "title_size": title_size,

            "text": text,  # raw text; HTML nutzt white-space: pre-wrap
            "text_font": text_font,
            "text_align": text_align,
            "text_color": text_color,
            "font_size": font_size,
            "min_font_size": min_font_size,
            "auto_fit": auto_fit,

            "plugin_settings": settings,
        }

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]

        try:
            image = self.render_image(dimensions, "helloworld.html", "helloworld.css", template_params)
        except Exception as e:
            logger.exception("Fehler beim Rendern des HelloWorld-Plugins")
            raise RuntimeError(f"Rendering-Fehler: {e}")

        if image is None:
            raise RuntimeError("Rendering fehlgeschlagen (kein Bild erzeugt). Bitte Logs prüfen.")

        return image