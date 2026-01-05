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

PRESETS = {
    # bewusst schlicht – passt gut zu ACEP und ist sehr lesbar
    "hint": {
        "title": "Hinweis",
        "title_color": ACEP_COLORS["black"],
        "title_size": 96,
        "panel_bg": ACEP_COLORS["yellow"],
        "frame": "thick",
        "frame_color": ACEP_COLORS["black"],
        "layout": "infoboard",
        "text_color": ACEP_COLORS["black"],
        "title_align": "center",
        "text_align": "center",
    },
    "alarm": {
        "title": "ALARM",
        "title_color": ACEP_COLORS["white"],
        "title_size": 110,
        "panel_bg": ACEP_COLORS["red"],
        "frame": "thick",
        "frame_color": ACEP_COLORS["black"],
        "layout": "infoboard",
        "text_color": ACEP_COLORS["white"],
        "title_align": "center",
        "text_align": "center",
    },
    "info": {
        "title": "Info",
        "title_color": ACEP_COLORS["white"],
        "title_size": 92,
        "panel_bg": ACEP_COLORS["blue"],
        "frame": "thin",
        "frame_color": ACEP_COLORS["white"],
        "layout": "infoboard",
        "text_color": ACEP_COLORS["white"],
        "title_align": "center",
        "text_align": "center",
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
        # --- Preset anwenden (überschreibt Default-Werte, aber lässt User-Inputs zu) ---
        preset_key = settings.get("preset", "custom")
        preset = PRESETS.get(preset_key) if preset_key and preset_key != "custom" else None

        # Helper: preset_value -> settings_value -> fallback
        def pick(key, fallback):
            if preset and key in preset:
                return settings.get(key, preset[key])
            return settings.get(key, fallback)

        # --- Layout/Panel ---
        layout = pick("layout", "center")  # "center" | "infoboard"
        panel_bg = pick("panel_bg", "none")
        frame = pick("frame", "none")      # "none" | "thin" | "thick"
        frame_color = pick("frame_color", "#000000")

        # --- Titel ---
        title = (pick("title", "") or "").strip()
        title_font = pick("title_font", "Inter")
        title_align = pick("title_align", "center")
        title_color = pick("title_color", "#000000")
        title_size = _as_int(pick("title_size", 96), 96, 20, 200)

        # --- Text (mehrzeilig) ---
        raw_text = (pick("text", "") or "").rstrip()
        if not raw_text and not title:
            raw_text = "Hello World 👋"

        # Zeilenumbrüche behalten; wir rendern im HTML mit white-space: pre-wrap
        text_font = pick("text_font", "Inter")
        text_align = pick("text_align", "center")
        text_color = pick("text_color", "#000000")
        font_size = _as_int(pick("font_size", 56), 56, 12, 160)
        min_font_size = _as_int(pick("min_font_size", 18), 18, 10, 120)
        min_font_size = min(min_font_size, font_size)

        auto_fit = _as_bool(pick("auto_fit", True), True)

        # --- Template params ---
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

            "text": raw_text,  # raw; HTML macht pre-wrap
            "text_font": text_font,
            "text_align": text_align,
            "text_color": text_color,
            "font_size": font_size,
            "min_font_size": min_font_size,
            "auto_fit": auto_fit,

            "plugin_settings": settings,  # global style settings (optional)
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