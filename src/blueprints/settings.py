from flask import Blueprint, request, jsonify, current_app, render_template, Response
from datetime import datetime, timedelta
import os
import pytz
import logging
import io

# Try to import cysystemd for journal reading (Linux only)
try:
    from cysystemd.reader import JournalReader, JournalOpenMode, Rule
    JOURNAL_AVAILABLE = True
except ImportError:
    JOURNAL_AVAILABLE = False
    # Define dummy classes for when cysystemd is not available
    class JournalOpenMode:
        SYSTEM = None
    class Rule:
        pass
    class JournalReader:
        def __init__(self, *args, **kwargs):
            pass


logger = logging.getLogger(__name__)
settings_bp = Blueprint("settings", __name__)

IMAGE_SETTING_KEYS = ("saturation", "contrast", "sharpness", "brightness")
IMAGE_SETTING_LIMITS = (0.0, 3.0)

@settings_bp.route('/settings')
def settings_page():
    device_config = current_app.config['DEVICE_CONFIG']
    return render_template('settings.html', device_settings=device_config.get_config())

@settings_bp.route('/settings/geraet')
def device_page():
    device_config = current_app.config['DEVICE_CONFIG']
    return render_template('settings_geraet.html', device_settings=device_config.get_config(),
                           timezones=sorted(pytz.all_timezones_set))

@settings_bp.route('/settings/bild')
def image_page():
    device_config = current_app.config['DEVICE_CONFIG']
    image_settings = device_config.get_config("image_settings", default={}) or {}
    values = {key: float(image_settings.get(key, 1.0)) for key in IMAGE_SETTING_KEYS}
    return render_template('settings_bild.html', image_settings=values)

@settings_bp.route('/settings/updates')
def updates_page():
    return render_template('settings_updates.html')

DEVICE_NAME_MAX_LENGTH = 40
ORIENTATIONS = ("horizontal", "vertical")
TIME_FORMATS = ("24h", "12h")

def validate_device_settings(data, timezones):
    """Prüft einzelne Geräteeinstellungen (nur die übergebenen) und gibt sie für device.json zurück.
    Wirft ValueError mit einer Meldung für die Oberfläche."""
    settings = {}
    if "name" in data:
        name = str(data["name"] or "").strip()
        if not name:
            raise ValueError("Bitte gib dem Gerät einen Namen.")
        if len(name) > DEVICE_NAME_MAX_LENGTH:
            raise ValueError(f"Der Name darf höchstens {DEVICE_NAME_MAX_LENGTH} Zeichen lang sein.")
        settings["name"] = name
    if "orientation" in data:
        if data["orientation"] not in ORIENTATIONS:
            raise ValueError("Unbekannte Ausrichtung.")
        settings["orientation"] = data["orientation"]
    if "time_format" in data:
        if data["time_format"] not in TIME_FORMATS:
            raise ValueError("Unbekanntes Zeitformat.")
        settings["time_format"] = data["time_format"]
    if "timezone" in data:
        if data["timezone"] not in timezones:
            raise ValueError(f"„{data['timezone']}“ ist keine bekannte Zeitzone. Wähle eine aus der Liste, z. B. Europe/Berlin.")
        settings["timezone"] = data["timezone"]
    for key in ("inverted_image", "log_system_stats"):
        if key in data:
            settings[key] = bool(data[key])
    if not settings:
        raise ValueError("Keine Einstellung übergeben.")
    return settings

@settings_bp.route('/settings/geraet', methods=['POST'])
def save_device_settings():
    """Speichert einzelne Geräteeinstellungen sofort (JSON, z. B. {"orientation": "vertical"})."""
    device_config = current_app.config['DEVICE_CONFIG']
    try:
        settings = validate_device_settings(request.get_json(silent=True) or {}, pytz.all_timezones_set)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    timezone_changed = "timezone" in settings and settings["timezone"] != device_config.get_config("timezone", default=None)
    device_config.update_config(settings)
    if timezone_changed:
        # Hintergrund-Task wecken, damit der Zeitplan mit der neuen Zeitzone rechnet
        current_app.config['REFRESH_TASK'].signal_config_change()
    return jsonify({"success": True, "message": "Gesichert"})

@settings_bp.route('/image_settings', methods=['GET'])
def get_image_settings():
    device_config = current_app.config['DEVICE_CONFIG']
    current = device_config.get_config("image_settings", default={}) or {}
    return jsonify({key: float(current.get(key, 1.0)) for key in IMAGE_SETTING_KEYS})

@settings_bp.route('/image_settings', methods=['POST'])
def save_image_settings():
    """Übernimmt nur die Bildeinstellungen, z. B. aus der Bildkalibrierung."""
    device_config = current_app.config['DEVICE_CONFIG']
    data = request.get_json(silent=True) or {}

    image_settings = dict(device_config.get_config("image_settings", default={}) or {})
    for key in IMAGE_SETTING_KEYS:
        if key not in data:
            continue
        try:
            value = float(data[key])
        except (TypeError, ValueError):
            return jsonify({"error": f"Ungültiger Wert für {key}"}), 400
        low, high = IMAGE_SETTING_LIMITS
        if not low <= value <= high:
            return jsonify({"error": f"{key} muss zwischen {low} und {high} liegen"}), 400
        image_settings[key] = round(value, 2)

    device_config.update_config({"image_settings": image_settings})
    return jsonify({"success": True, "message": "Bildeinstellungen übernommen."})

@settings_bp.route('/shutdown', methods=['POST'])
def shutdown():
    data = request.get_json() or {}
    if data.get("reboot"):
        logger.info("Reboot requested")
        os.system("sudo reboot")
    else:
        logger.info("Shutdown requested")
        os.system("sudo shutdown -h now")
    return jsonify({"success": True})

@settings_bp.route('/download-logs')
def download_logs():
    try:
        buffer = io.StringIO()
        
        # Get 'hours' from query parameters, default to 2 if not provided or invalid
        hours_str = request.args.get('hours', '2')
        try:
            hours = int(hours_str)
        except ValueError:
            hours = 2
        since = datetime.now() - timedelta(hours=hours)

        if not JOURNAL_AVAILABLE:
            # Return a message when running in development mode without systemd
            buffer.write("Log-Download im Entwicklungsmodus nicht verfügbar (cysystemd ist nicht installiert).\n")
            buffer.write(f"Normalerweise enthält diese Datei die Logs des InkyPi-Dienstes der letzten {hours} Stunden.\n")
            buffer.write("\nDie Flask-Entwicklungslogs findest du in der Terminalausgabe.\n")
        else:
            reader = JournalReader()
            reader.open(JournalOpenMode.SYSTEM)
            reader.add_filter(Rule("_SYSTEMD_UNIT", "inkypi.service"))
            reader.seek_realtime_usec(int(since.timestamp() * 1_000_000))

            for record in reader:
                try:
                    ts = datetime.fromtimestamp(record.get_realtime_usec() / 1_000_000)
                    formatted_ts = ts.strftime("%b %d %H:%M:%S")
                except Exception:
                    formatted_ts = "??? ?? ??:??:??"

                data = record.data
                hostname = data.get("_HOSTNAME", "unknown-host")
                identifier = data.get("SYSLOG_IDENTIFIER") or data.get("_COMM", "?")
                pid = data.get("_PID", "?")
                msg = data.get("MESSAGE", "").rstrip()

                # Format the log entry similar to the journalctl default output
                buffer.write(f"{formatted_ts} {hostname} {identifier}[{pid}]: {msg}\n")

        buffer.seek(0)
        # Add date and time to the filename
        now_str = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"inkypi_{now_str}.log"
        return Response(
            buffer.read(),
            mimetype="text/plain",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )

    except Exception as e:
        logger.error(f"Fehler beim Lesen der Logs: {e}")
        return Response(f"Fehler beim Lesen der Logs: {e}", status=500, mimetype="text/plain")

