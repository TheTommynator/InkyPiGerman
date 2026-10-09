import fnmatch
import json
import logging
import threading
import time

from utils.image_utils import resize_image, change_orientation, apply_image_enhancement
from display.mock_display import MockDisplay

logger = logging.getLogger(__name__)

# Try to import hardware displays, but don't fail if they're not available
try:
    from display.inky_display import InkyDisplay
except ImportError:
    logger.info("Inky display not available, hardware support disabled")

try:
    from display.waveshare_display import WaveshareDisplay
except ImportError:
    logger.info("Waveshare display not available, hardware support disabled")

class DisplayManager:

    """Manages the display and rendering of images."""

    def __init__(self, device_config):

        """
        Initializes the display manager and selects the correct display type 
        based on the configuration.

        Args:
            device_config (object): Configuration object containing display settings.

        Raises:
            ValueError: If an unsupported display type is specified.
        """
        
        self.device_config = device_config

        # Status der Display-Aktualisierung für die Weboberfläche
        self._status_lock = threading.Lock()
        self._refresh_started = None
        self._refresh_finished = None
        self._last_error = None
        self._last_duration = device_config.get_config("last_display_refresh_seconds", default=None)
     
        display_type = device_config.get_config("display_type", default="inky")

        if display_type == "mock":
            self.display = MockDisplay(device_config)
        elif display_type == "inky":
            self.display = InkyDisplay(device_config)
        elif fnmatch.fnmatch(display_type, "epd*in*"):  
            # derived from waveshare epd - we assume here that will be consistent
            # otherwise we will have to enshring the manufacturer in the 
            # display_type and then have a display_model parameter.  Will leave
            # that for future use if the need arises.
            #
            # see https://github.com/waveshareteam/e-Paper
            self.display = WaveshareDisplay(device_config)
        else:
            raise ValueError(f"Unsupported display type: {display_type}")

    def display_image(self, image, image_settings=[]):
        
        """
        Delegates image rendering to the appropriate display instance.

        Args:
            image (PIL.Image): The image to be displayed.
            image_settings (list, optional): List of settings to modify image rendering.

        Raises:
            ValueError: If no valid display instance is found.
        """

        if not hasattr(self, "display"):
            raise ValueError("No valid display instance initialized.")

        with self._status_lock:
            self._refresh_started = time.monotonic()
            self._last_error = None
        try:
            self._render(image, image_settings)
        except Exception as e:
            with self._status_lock:
                self._refresh_started = None
                self._last_error = str(e) or type(e).__name__
            raise

        with self._status_lock:
            finished = time.monotonic()
            self._last_duration = round(finished - self._refresh_started, 1)
            self._refresh_started = None
            self._refresh_finished = finished
        # Dauer merken, damit die Schätzung auch nach einem Neustart passt
        self.device_config.update_value("last_display_refresh_seconds", self._last_duration)
        logger.info(f"Display refresh finished in {self._last_duration}s")

    def get_status(self):
        """Liefert, ob das Display gerade aktualisiert wird, und die Zeiten dazu (in Sekunden)."""
        with self._status_lock:
            now = time.monotonic()
            started, finished = self._refresh_started, self._refresh_finished
            return {
                "refreshing": started is not None,
                "elapsed_seconds": round(now - started, 1) if started is not None else None,
                "expected_seconds": self._last_duration,
                "seconds_since_update": round(now - finished, 1) if finished is not None else None,
                "error": self._last_error,
            }

    def _render(self, image, image_settings):
        # Save the image
        logger.info(f"Saving image to {self.device_config.current_image_file}")
        image.save(self.device_config.current_image_file)

        # Resize and adjust orientation
        image = change_orientation(image, self.device_config.get_config("orientation"))
        image = resize_image(image, self.device_config.get_resolution(), image_settings)
        if self.device_config.get_config("inverted_image"): image = image.rotate(180)
        # Plugins wie die Bildkalibrierung wenden die Werte selbst an
        if "skip-enhancement" not in image_settings:
            image = apply_image_enhancement(image, self.device_config.get_config("image_settings"))

        # Pass to the concrete instance to render to the device.
        self.display.display_image(image, image_settings)