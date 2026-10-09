from plugins.base_plugin.base_plugin import BasePlugin
from PIL import Image
from datetime import datetime, timezone
import logging
import pytz

logger = logging.getLogger(__name__)

MONTHS_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
             "August", "September", "Oktober", "November", "Dezember"]

class Countdown(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params['style_settings'] = True
        return template_params

    def generate_image(self, settings, device_config):
        title = settings.get('title')
        countdown_date_str = settings.get('date')

        if not countdown_date_str:
            raise RuntimeError("Bitte ein Datum angeben.")

        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]
        
        timezone = device_config.get_config("timezone", default="America/New_York")
        tz = pytz.timezone(timezone)
        current_time = datetime.now(tz)

        countdown_date = datetime.strptime(countdown_date_str, "%Y-%m-%d")
        countdown_date = tz.localize(countdown_date)

        day_count = (countdown_date.date() - current_time.date()).days
        label = "Tage verbleibend" if day_count > 0 else "Tage vergangen"

        template_params = {
            "title": title,
            "date": f"{countdown_date.day}. {MONTHS_DE[countdown_date.month - 1]} {countdown_date.year}",
            "day_count": abs(day_count),
            "label": label,
            "plugin_settings": settings
        }

        image = self.render_image(dimensions, "countdown.html", "countdown.css", template_params)
        return image