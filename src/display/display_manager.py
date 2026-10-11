import fnmatch
import json
import logging
import threading
import time

from utils.image_utils import resize_image, change_orientation, apply_image_enhancement
from display.mock_display import MockDisplay

logger = logging.getLogger(__name__)

# Schritte einer Aktualisierung, wie sie in der Weboberfläche erscheinen
PHASE_LABELS = {
    "erzeugen": "Bild wird erzeugt",
    "vorbereiten": "Bild wird vorbereitet",
    "aufwecken": "Display wird aufgeweckt",
    "loeschen": "Altes Bild wird gelöscht",
    "farben": "Farben werden umgerechnet",
    "aufbauen": "Neue Farben werden aufgebaut",
    "schlafen": "Display geht in den Ruhezustand",
}


def _load_phase_plan(value):
    """Gespeicherte Schrittdauern [[Schritt, Sekunden], …] einlesen; Unbrauchbares ignorieren."""
    plan = []
    for step in value if isinstance(value, list) else []:
        try:
            key, seconds = step
            plan.append((str(key), float(seconds)))
        except (TypeError, ValueError):
            continue
    return plan

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
        self._job_title = None        # was gerade angezeigt wird (z. B. Name der Ansicht)
        self._job_started = None      # Beginn von Erzeugen + Anzeigen
        self._refresh_started = None  # Beginn der eigentlichen Display-Aktualisierung
        self._refresh_finished = None
        self._phase = None
        self._phase_started = None
        self._run_phases = []         # [(Schritt, Sekunden)] der laufenden Aktualisierung
        self._last_error = None
        self._last_duration = device_config.get_config("last_display_refresh_seconds", default=None)
        self._phase_plan = _load_phase_plan(device_config.get_config("display_phase_seconds", default=None))
     
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

        # Die Treiber melden ihre Schritte („Altes Bild wird gelöscht“ …)
        self.display.phase_callback = self.set_phase

    def display_image(self, image, image_settings=[], title=None):
        
        """
        Delegates image rendering to the appropriate display instance.

        Args:
            image (PIL.Image): The image to be displayed.
            image_settings (list, optional): List of settings to modify image rendering.
            title (str, optional): Was angezeigt wird, für die Statusanzeige in der Weboberfläche.

        Raises:
            ValueError: If no valid display instance is found.
        """

        if not hasattr(self, "display"):
            raise ValueError("No valid display instance initialized.")

        with self._status_lock:
            now = time.monotonic()
            if self._job_started is None:
                # Aufruf ohne vorheriges Erzeugen (z. B. Startbild)
                self._job_started = now
                self._job_title = None
            if title:
                self._job_title = title
            self._refresh_started = now
            self._run_phases = []
            self._last_error = None
            self._enter_phase("vorbereiten", now)
        try:
            self._render(image, image_settings)
        except Exception as e:
            self._end_job(error=str(e) or type(e).__name__)
            raise

        with self._status_lock:
            finished = time.monotonic()
            self._enter_phase(None, finished)
            self._last_duration = round(finished - self._refresh_started, 1)
            if self._run_phases:
                # Meldet ein Treiber einen Schritt mehrfach, zählt er einmal mit der Gesamtdauer
                totals = {}
                for key, seconds in self._run_phases:
                    totals[key] = totals.get(key, 0.0) + seconds
                self._phase_plan = [(key, round(seconds, 1)) for key, seconds in totals.items()]
            self._refresh_finished = finished
        self._end_job()
        # Dauern merken, damit die Schätzung auch nach einem Neustart passt
        self.device_config.update_value("last_display_refresh_seconds", self._last_duration)
        self.device_config.update_value("display_phase_seconds", [list(step) for step in self._phase_plan])
        logger.info(f"Display refresh finished in {self._last_duration}s | steps: {self._phase_plan}")

    def begin_job(self, title=None):
        """Ein neues Bild wird erzeugt (Plugin holt Daten); die Anzeige folgt ggf. mit display_image()."""
        with self._status_lock:
            if self._refresh_started is not None:
                # Das Display baut noch das vorige Bild auf – dessen Status bleibt sichtbar
                return
            now = time.monotonic()
            self._job_title = title
            self._job_started = now
            self._last_error = None
            self._enter_phase("erzeugen", now)

    def end_job(self, error=None):
        """Beendet einen Auftrag, der nicht (mehr) bis zum Display kommt – z. B. weil das Bild gleich blieb."""
        with self._status_lock:
            if self._refresh_started is not None:
                return
        self._end_job(error)

    def _end_job(self, error=None):
        with self._status_lock:
            self._job_title = None
            self._job_started = None
            self._refresh_started = None
            self._phase = None
            self._phase_started = None
            self._run_phases = []
            if error:
                self._last_error = error

    def set_phase(self, key):
        """Wird von den Display-Treibern aufgerufen, wenn ein neuer Schritt beginnt."""
        with self._status_lock:
            if self._job_started is not None:
                self._enter_phase(key, time.monotonic())

    def _enter_phase(self, key, now):
        if key is not None and key == self._phase:
            return
        # Dauer des bisherigen Schritts für die nächste Schätzung festhalten (nur Display-Schritte)
        if self._phase and self._phase != "erzeugen" and self._phase_started is not None:
            self._run_phases.append((self._phase, now - self._phase_started))
        self._phase = key
        self._phase_started = now if key else None

    def get_status(self):
        """Liefert, ob das Display gerade aktualisiert wird, welcher Schritt läuft und die Zeiten dazu (in Sekunden)."""
        with self._status_lock:
            now = time.monotonic()
            started, finished = self._refresh_started, self._refresh_finished
            refreshing = started is not None
            status = {
                "busy": self._job_started is not None,
                "refreshing": refreshing,
                "title": self._job_title,
                "phase": PHASE_LABELS.get(self._phase, self._phase) if self._phase else None,
                "elapsed_seconds": round(now - started, 1) if refreshing else None,
                "expected_seconds": self._last_duration,
                "remaining_seconds": None,
                "step": None,
                "steps": None,
                "seconds_since_update": round(now - finished, 1) if finished is not None else None,
                "error": self._last_error,
            }
            if refreshing and self._phase_plan:
                status.update(self._estimate(now))
            return status

    def _estimate(self, now):
        """Restzeit und Schrittnummer anhand der Dauern der letzten Aktualisierung."""
        plan = dict(self._phase_plan)
        done = {key for key, _ in self._run_phases}
        current = self._phase
        remaining = sum(seconds for key, seconds in self._phase_plan if key not in done and key != current)
        if current in plan:
            remaining += max(0.0, plan[current] - (now - self._phase_started))
        keys = [key for key, _ in self._phase_plan]
        result = {"remaining_seconds": round(remaining, 1)}
        if current in keys:
            result.update({"step": keys.index(current) + 1, "steps": len(keys)})
        return result

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