import threading
import time
import os
import logging
import psutil
import pytz
from datetime import datetime, timezone
from plugins.plugin_registry import get_plugin_instance
from utils.image_utils import compute_image_hash
from model import RefreshInfo, PlaylistManager
from zeitplaner import current_segment, needs_refresh, next_wakeup, retry_at
from PIL import Image

logger = logging.getLogger(__name__)

# Grenzen für das Warten im Zeitplan-Betrieb (Sekunden)
MIN_SCHEDULE_SLEEP = 1
MAX_SCHEDULE_SLEEP = 60 * 60

class RefreshTask:
    """Handles the logic for refreshing the display using a backgroud thread."""

    def __init__(self, device_config, display_manager):
        self.device_config = device_config
        self.display_manager = display_manager

        self.thread = None
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        self.running = False
        self.manual_update_request = None
        # Fehlgeschlagene Ansicht im Zeitplan: (Ansicht-ID, Abschnittsbeginn, nächster Versuch)
        self.schedule_failure = None
        # Von Hand angezeigtes Bild (Plugin-Seite) bleibt im Zeitplan-Betrieb bis zu diesem Zeitpunkt stehen
        self.manual_hold_until = None

    def start(self):
        """Starts the background thread for refreshing the display."""
        if not self.thread or not self.thread.is_alive():
            logger.info("Starting refresh task")
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.running = True
            self.thread.start()

    def stop(self):
        """Stops the refresh task by notifying the background thread to exit."""
        with self.condition:
            self.running = False
            self.condition.notify_all()  # Wake the thread to let it exit
        if self.thread:
            logger.info("Stopping refresh task")
            self.thread.join()

    def _run(self):
        """Background task that manages the periodic refresh of the display.

        This function runs in a loop, sleeping for a configured duration (`plugin_cycle_interval_seconds`) or until
        manually triggered via `manual_update()`. Detrmines the next plugin to refresh based on active playlists and 
        updates the display accordingly.

        Workflow:
        1. Waits for the configured sleep duration or until notified of a manual update.
        2. Checks if a manual update has been requested:
        - If so, refreshes the specified plugin immediately.
        3. Otherwise, determines the next plugin to refresh based on the active playlist and generates an image.
        4. Compares the image hash with the last displayed image hash.
        - If the image has changed, updates the display.
        - If the image is the same, skips the refresh.
        5. Updates the refresh metadata in the device configuration.
        6. Repeats the process until `stop()` is called.

        Handles any exceptions that occur during the refresh process and ensures the refresh event is set 
        to indicate completion.

        Exceptions:
        - Captures and logs any unexpected errors during execution to prevent the thread from exiting.
        """
        while True:
            request = None
            pending_display = None
            refresh_action = None
            try:
                with self.condition:
                    sleep_time = self._sleep_seconds()

                    # Wait for sleep_time or until notified (a request may already be waiting
                    # if it arrived while the display was busy)
                    if not self.manual_update_request and self.running:
                        self.condition.wait(timeout=sleep_time)

                    # Exit if `stop()` is called
                    if not self.running:
                        break

                    playlist_manager = self.device_config.get_playlist_manager()
                    latest_refresh = self.device_config.get_refresh_info()
                    current_dt = self._get_current_datetime()

                    refresh_action = None
                    if self.manual_update_request:
                        # handle immediate update request
                        logger.info("Manual update requested")
                        request = self.manual_update_request
                        refresh_action = request.action
                        self.manual_update_request = None
                    else:

                        if self.device_config.get_config("log_system_stats"):
                            self.log_system_stats()

                        if self.device_config.is_schedule_active():
                            refresh_action = self._determine_view_refresh(current_dt)
                        else:
                            # handle refresh based on playlists
                            logger.info(f"Running interval refresh check. | current_time: {current_dt.strftime('%Y-%m-%d %H:%M:%S')}")
                            playlist, plugin_instance = self._determine_next_plugin(playlist_manager, latest_refresh, current_dt)
                            if plugin_instance:
                                refresh_action = PlaylistRefresh(playlist, plugin_instance)

                    if refresh_action:
                        plugin_config = self.device_config.get_plugin(refresh_action.get_plugin_id())
                        if plugin_config is None:
                            raise ValueError(f"Plugin '{refresh_action.get_plugin_id()}' nicht gefunden")
                        plugin = get_plugin_instance(plugin_config)
                        image = refresh_action.execute(plugin, self.device_config, current_dt)
                        if isinstance(refresh_action, ViewRefresh):
                            self.schedule_failure = None
                        if request:
                            self._remember_manual(refresh_action, current_dt)
                        image_hash = compute_image_hash(image)

                        refresh_info = refresh_action.get_refresh_info()
                        refresh_info.update({"refresh_time": current_dt.isoformat(), "image_hash": image_hash})
                        # check if image is the same as current image
                        if image_hash != latest_refresh.image_hash:
                            logger.info(f"Updating display. | refresh_info: {refresh_info}")
                            pending_display = (image, plugin.config.get("image_settings", []), latest_refresh)
                        else:
                            logger.info(f"Image already displayed, skipping refresh. | refresh_info: {refresh_info}")

                        # update latest refresh data in the device config
                        self.device_config.refresh_info = RefreshInfo(**refresh_info)
                        self.device_config.write_config()

            except Exception as e:
                logger.exception('Exception during refresh')
                if request:
                    request.exception = e
                elif isinstance(refresh_action, ViewRefresh):
                    self._remember_failure(refresh_action)
                continue
            finally:
                # The image is ready: a waiting web request can return now, the
                # (slow) e-paper refresh continues in the background.
                if request:
                    request.display_started = pending_display is not None
                    request.done.set()

            if pending_display:
                self._show(*pending_display)

    def _show(self, image, image_settings, previous_refresh_info):
        """Sends the image to the display without holding the lock, so the web interface stays usable."""
        try:
            self.display_manager.display_image(image, image_settings=image_settings)
        except Exception:
            logger.exception('Exception while updating the display')
            # Show the image again on the next refresh instead of skipping it as "already displayed"
            with self.condition:
                self.device_config.refresh_info = previous_refresh_info
                self.device_config.write_config()

    def manual_update(self, refresh_action):
        """Manually triggers an update for the specified plugin id and plugin settings by notifying the background process.

        Returns as soon as the image has been generated; the display itself is updated in the background.
        The return value tells whether a display update was started (False if the image was already shown).
        """
        if self.running:
            request = ManualUpdateRequest(refresh_action)
            with self.condition:
                self.manual_update_request = request
                self.condition.notify_all()  # Wake the thread to process manual update

            request.done.wait()
            if request.exception:
                raise request.exception
            return request.display_started
        else:
            logger.warn("Background refresh task is not running, unable to do a manual update")

    def signal_config_change(self):
        """Notify the background thread that config has changed (e.g., interval updated)."""
        if self.running:
            with self.condition:
                self.condition.notify_all()

    def _get_current_datetime(self):
        """Retrieves the current datetime based on the device's configured timezone."""
        tz_str = self.device_config.get_config("timezone", default="UTC")
        return datetime.now(pytz.timezone(tz_str))

    def _sleep_seconds(self):
        """Wie lange bis zur nächsten Prüfung gewartet wird.

        Mit Playlists: das Plugin-Wechselintervall. Mit dem Zeitplan: bis zum nächsten
        Abschnittswechsel oder zur nächsten Datenaktualisierung der angezeigten Ansicht.
        """
        if not self.device_config.is_schedule_active():
            return self.device_config.get_config("plugin_cycle_interval_seconds", default=60*60)
        try:
            now = self._get_current_datetime().replace(tzinfo=None)
            schedule = self.device_config.get_schedule()
            wakeup = next_wakeup(schedule, now)
            if self.manual_hold_until and now < self.manual_hold_until:
                wakeup = self.manual_hold_until
            failure = self._current_failure(schedule, now)
            if failure:
                segment, retry = failure
                wakeup = retry or segment.end
            seconds = (wakeup - now).total_seconds() + 1
        except Exception:
            logger.exception("Zeitplan: nächster Zeitpunkt konnte nicht berechnet werden")
            seconds = 60
        return min(MAX_SCHEDULE_SLEEP, max(MIN_SCHEDULE_SLEEP, seconds))

    def _current_failure(self, schedule, now):
        """(Abschnitt, nächster Versuch), wenn die Ansicht im aktuellen Abschnitt fehlgeschlagen ist."""
        if not self.schedule_failure:
            return None
        view_id, segment_start, retry = self.schedule_failure
        segment = current_segment(schedule, now)
        if segment.view and segment.view.id == view_id and segment.start == segment_start:
            return segment, retry
        self.schedule_failure = None
        return None

    def _remember_failure(self, action):
        """Fehler beim Erzeugen: das letzte Bild bleibt stehen, später neuer Versuch."""
        retry = retry_at(action.now, action.segment)
        self.schedule_failure = (action.view.id, action.segment.start, retry)
        when = retry.strftime('%H:%M') if retry else "beim nächsten Abschnitt"
        logger.warning(f"Zeitplan: Ansicht '{action.view.name}' fehlgeschlagen, das letzte Bild bleibt. Neuer Versuch: {when}")

    def _remember_manual(self, action, current_dt):
        """„Jetzt anzeigen“ auf der Plugin-Seite: Das Bild bleibt bis zum Ende des aktuellen
        Abschnitts stehen, statt beim nächsten Aufwachen gleich wieder ersetzt zu werden.
        Eine Ansicht aus dem Zeitplan („Jetzt anzeigen“ in den Ansichten) hebt das auf."""
        if not self.device_config.is_schedule_active():
            return
        if isinstance(action, ManualRefresh):
            now = current_dt.replace(tzinfo=None)
            self.manual_hold_until = current_segment(self.device_config.get_schedule(), now).end
        else:
            self.manual_hold_until = None

    def _determine_view_refresh(self, current_dt):
        """Bestimmt anhand des Zeitplans, welche Ansicht jetzt angezeigt wird."""
        now = current_dt.replace(tzinfo=None)
        schedule = self.device_config.get_schedule()
        segment = current_segment(schedule, now)
        logger.info(f"Zeitplan: {segment} | current_time: {now:%Y-%m-%d %H:%M:%S}")
        if self.manual_hold_until:
            if now < self.manual_hold_until:
                logger.info(f"Zeitplan: von Hand angezeigtes Bild bleibt bis {self.manual_hold_until:%H:%M}")
                return None
            self.manual_hold_until = None
        if segment.view is None:
            return None
        failure = self._current_failure(schedule, now)
        if failure and (failure[1] is None or now < failure[1]):
            return None
        return ViewRefresh(segment.view, segment, now)

    def _determine_next_plugin(self, playlist_manager, latest_refresh_info, current_dt):
        """Determines the next plugin to refresh based on the active playlist, plugin cycle interval, and current time."""
        playlist = playlist_manager.determine_active_playlist(current_dt)
        if not playlist:
            playlist_manager.active_playlist = None
            logger.info(f"No active playlist determined.")
            return None, None

        playlist_manager.active_playlist = playlist.name
        if not playlist.plugins:
            logger.info(f"Active playlist '{playlist.name}' has no plugins.")
            return None, None

        latest_refresh_dt = latest_refresh_info.get_refresh_datetime()
        plugin_cycle_interval = self.device_config.get_config("plugin_cycle_interval_seconds", default=3600)
        should_refresh = PlaylistManager.should_refresh(latest_refresh_dt, plugin_cycle_interval, current_dt)

        if not should_refresh:
            latest_refresh_str = latest_refresh_dt.strftime('%Y-%m-%d %H:%M:%S') if latest_refresh_dt else "None"
            logger.info(f"Not time to update display. | latest_update: {latest_refresh_str} | plugin_cycle_interval: {plugin_cycle_interval}")
            return None, None

        plugin = playlist.get_next_plugin()
        logger.info(f"Determined next plugin. | active_playlist: {playlist.name} | plugin_instance: {plugin.name}")

        return playlist, plugin
    
    def log_system_stats(self):
        metrics = {
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory_percent': psutil.virtual_memory().percent,
            'disk_percent': psutil.disk_usage('/').percent,
            'load_avg_1_5_15': os.getloadavg(),
            'swap_percent': psutil.swap_memory().percent,
            'net_io': {
                'bytes_sent': psutil.net_io_counters().bytes_sent,
                'bytes_recv': psutil.net_io_counters().bytes_recv
            }
        }

        logger.info(f"System Stats: {metrics}")

class ManualUpdateRequest:
    """A manual update waiting for the background thread, with its own completion signal."""

    def __init__(self, action):
        self.action = action
        self.done = threading.Event()
        self.exception = None
        self.display_started = False

class RefreshAction:
    """Base class for a refresh action. Subclasses should override the methods below."""
    
    def refresh(self, plugin, device_config, current_dt):
        """Perform a refresh operation and return the updated image."""
        raise NotImplementedError("Subclasses must implement the refresh method.")
    
    def get_refresh_info(self):
        """Return refresh metadata as a dictionary."""
        raise NotImplementedError("Subclasses must implement the get_refresh_info method.")
    
    def get_plugin_id(self):
        """Return the plugin ID associated with this refresh."""
        raise NotImplementedError("Subclasses must implement the get_plugin_id method.")

class ManualRefresh(RefreshAction):
    """Performs a manual refresh based on a plugin's ID and its associated settings.
    
    Attributes:
        plugin_id (str): The ID of the plugin to refresh.
        plugin_settings (dict): The settings for the manual refresh.
    """

    def __init__(self, plugin_id: str, plugin_settings: dict):
        self.plugin_id = plugin_id
        self.plugin_settings = plugin_settings

    def execute(self, plugin, device_config, current_dt: datetime):
        """Performs a manual refresh using the stored plugin ID and settings."""
        return plugin.generate_image(self.plugin_settings, device_config)

    def get_refresh_info(self):
        """Return refresh metadata as a dictionary."""
        return {"refresh_type": "Manual Update", "plugin_id": self.plugin_id}

    def get_plugin_id(self):
        """Return the plugin ID associated with this refresh."""
        return self.plugin_id

class PlaylistRefresh(RefreshAction):
    """Performs a refresh using a plugin instance within a playlist context.

    Attributes:
        playlist: The playlist object associated with the refresh.
        plugin_instance: The plugin instance to refresh.
    """

    def __init__(self, playlist, plugin_instance, force=False):
        self.playlist = playlist
        self.plugin_instance = plugin_instance
        self.force = force

    def get_refresh_info(self):
        """Return refresh metadata as a dictionary."""
        return {
            "refresh_type": "Playlist",
            "playlist": self.playlist.name,
            "plugin_id": self.plugin_instance.plugin_id,
            "plugin_instance": self.plugin_instance.name
        }

    def get_plugin_id(self):
        """Return the plugin ID associated with this refresh."""
        return self.plugin_instance.plugin_id

    def execute(self, plugin, device_config, current_dt: datetime):
        """Performs a refresh for the specified plugin instance within its playlist context."""
        # Determine the file path for the plugin's image
        plugin_image_path = os.path.join(device_config.plugin_image_dir, self.plugin_instance.get_image_path())

        # Check if a refresh is needed based on the plugin instance's criteria
        if self.plugin_instance.should_refresh(current_dt) or self.force:
            logger.info(f"Refreshing plugin instance. | plugin_instance: '{self.plugin_instance.name}'") 
            # Generate a new image
            image = plugin.generate_image(self.plugin_instance.settings, device_config)
            image.save(plugin_image_path)
            self.plugin_instance.latest_refresh_time = current_dt.isoformat()
        else:
            logger.info(f"Not time to refresh plugin instance, using latest image. | plugin_instance: {self.plugin_instance.name}.")
            # Load the existing image from disk
            with Image.open(plugin_image_path) as img:
                image = img.copy()

        return image


class ViewRefresh(RefreshAction):
    """Zeigt eine Ansicht aus dem Zeitplan an und holt bei Bedarf neue Daten.

    Attributes:
        view: Die Ansicht (zeitplan.View).
        segment: Der Abschnitt des Tagesplans, in dem sie läuft (None bei „Jetzt anzeigen“).
        now: Zeitpunkt der Entscheidung (naive Ortszeit).
        force: Daten in jedem Fall neu holen.
    """

    def __init__(self, view, segment=None, now=None, force=False):
        self.view = view
        self.segment = segment
        self.now = now
        self.force = force

    def get_refresh_info(self):
        return {
            "refresh_type": "Ansicht",
            "plugin_id": self.view.plugin_id,
            "plugin_instance": self.view.name,
        }

    def get_plugin_id(self):
        return self.view.plugin_id

    def execute(self, plugin, device_config, current_dt: datetime):
        image_path = os.path.join(device_config.plugin_image_dir, self.view.get_image_path())
        now = current_dt.replace(tzinfo=None)
        due = (self.force or self.segment is None or not os.path.exists(image_path)
               or needs_refresh(self.view, now, self.segment))
        if due:
            logger.info(f"Ansicht holt neue Daten. | view: '{self.view.name}'")
            image = plugin.generate_image(self.view.settings, device_config)
            if image is None:
                raise RuntimeError(f"Das Plugin hat für „{self.view.name}“ kein Bild geliefert")
            image.save(image_path)
            self.view.latest_refresh_time = current_dt.isoformat()
        else:
            logger.info(f"Ansicht nutzt vorhandenes Bild. | view: '{self.view.name}'")
            with Image.open(image_path) as img:
                image = img.copy()
        return image
