from flask import Blueprint, request, jsonify, current_app, render_template, Response
from utils.time_utils import calculate_seconds
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

@settings_bp.route('/settings')
def settings_page():
    device_config = current_app.config['DEVICE_CONFIG']
    timezones = sorted(pytz.all_timezones_set)
    return render_template('settings.html', device_settings=device_config.get_config(), timezones = timezones)

@settings_bp.route('/save_settings', methods=['POST'])
def save_settings():
    device_config = current_app.config['DEVICE_CONFIG']

    try:
        form_data = request.form.to_dict()

        unit, interval, time_format = form_data.get('unit'), form_data.get("interval"), form_data.get("timeFormat")
        if not unit or unit not in ["minute", "hour"]:
            return jsonify({"error": "Einheit des Plugin-Wechselintervalls fehlt"}), 400
        if not interval or not interval.isnumeric():
            return jsonify({"error": "Wechselintervall fehlt"}), 400
        if not form_data.get("timezoneName"):
            return jsonify({"error": "Zeitzone fehlt"}), 400
        if not time_format or time_format not in ["12h", "24h"]:
            return jsonify({"error": "Zeitformat fehlt"}), 400
        previous_interval_seconds = device_config.get_config("plugin_cycle_interval_seconds")
        previous_timezone = device_config.get_config("timezone", default=None)
        plugin_cycle_interval_seconds = calculate_seconds(int(interval), unit)
        if plugin_cycle_interval_seconds > 86400 or plugin_cycle_interval_seconds <= 0:
            return jsonify({"error": "Das Plugin-Wechselintervall muss kürzer als 24 Stunden sein"}), 400

        settings = {
            "name": form_data.get("deviceName"),
            "orientation": form_data.get("orientation"),
            "inverted_image": form_data.get("invertImage"),
            "log_system_stats": form_data.get("logSystemStats"),
            "timezone": form_data.get("timezoneName"),
            "time_format": form_data.get("timeFormat"),
            "plugin_cycle_interval_seconds": plugin_cycle_interval_seconds,
            "image_settings": {
                "saturation": float(form_data.get("saturation", "1.0")),
                "brightness": float(form_data.get("brightness", "1.0")),
                "sharpness": float(form_data.get("sharpness", "1.0")),
                "contrast": float(form_data.get("contrast", "1.0"))
            }
        }
        device_config.update_config(settings)

        if plugin_cycle_interval_seconds != previous_interval_seconds or settings["timezone"] != previous_timezone:
            # wake the background thread up to signal interval or timezone change
            refresh_task = current_app.config['REFRESH_TASK']
            refresh_task.signal_config_change()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        return jsonify({"error": f"Ein Fehler ist aufgetreten: {str(e)}"}), 500
    return jsonify({"success": True, "message": "Einstellungen gespeichert."})

IMAGE_SETTING_KEYS = ("saturation", "contrast", "sharpness", "brightness")
IMAGE_SETTING_LIMITS = (0.0, 3.0)

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

