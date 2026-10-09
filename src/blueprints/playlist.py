from flask import Blueprint, request, jsonify, current_app, render_template
from utils.time_utils import calculate_seconds
import json
from datetime import datetime, timedelta
import os
import logging
from utils.app_utils import resolve_path, handle_request_files, parse_form


logger = logging.getLogger(__name__)
playlist_bp = Blueprint("playlist", __name__)

@playlist_bp.route('/add_plugin', methods=['POST'])
def add_plugin():
    device_config = current_app.config['DEVICE_CONFIG']
    refresh_task = current_app.config['REFRESH_TASK']
    playlist_manager = device_config.get_playlist_manager()

    try:
        plugin_settings = parse_form(request.form)
        refresh_settings = json.loads(plugin_settings.pop("refresh_settings"))
        plugin_id = plugin_settings.pop("plugin_id")

        playlist = refresh_settings.get('playlist')
        instance_name = refresh_settings.get('instance_name')
        if not playlist:
            return jsonify({"error": "Name der Playlist fehlt"}), 400
        if not instance_name or not instance_name.strip():
            return jsonify({"error": "Name der Instanz fehlt"}), 400
        if not all(char.isalpha() or char.isspace() or char.isnumeric() for char in instance_name):
            return jsonify({"error": "Der Name der Instanz darf nur Buchstaben, Ziffern und Leerzeichen enthalten"}), 400
        refresh_type = refresh_settings.get('refreshType')
        if not refresh_type or refresh_type not in ["interval", "scheduled"]:
            return jsonify({"error": "Art der Aktualisierung fehlt"}), 400

        existing = playlist_manager.find_plugin(plugin_id, instance_name)
        if existing:
            return jsonify({"error": f"Plugin-Instanz '{instance_name}' existiert bereits"}), 400

        if refresh_type == "interval":
            unit, interval = refresh_settings.get('unit'), refresh_settings.get("interval")
            if not unit or unit not in ["minute", "hour", "day"]:
                return jsonify({"error": "Einheit des Aktualisierungsintervalls fehlt"}), 400
            if not interval:
                return jsonify({"error": "Aktualisierungsintervall fehlt"}), 400
            refresh_interval_seconds = calculate_seconds(int(interval), unit)
            refresh_config = {"interval": refresh_interval_seconds}
        else:
            refresh_time = refresh_settings.get('refreshTime')
            if not refresh_settings.get('refreshTime'):
                return jsonify({"error": "Uhrzeit der Aktualisierung fehlt"}), 400
            refresh_config = {"scheduled": refresh_time}

        plugin_settings.update(handle_request_files(request.files))
        plugin_dict = {
            "plugin_id": plugin_id,
            "refresh": refresh_config,
            "plugin_settings": plugin_settings,
            "name": instance_name
        }
        result = playlist_manager.add_plugin_to_playlist(playlist, plugin_dict)
        if not result:
            return jsonify({"error": "Hinzufügen zur Playlist fehlgeschlagen"}), 500

        device_config.write_config()
    except Exception as e:
        return jsonify({"error": f"Ein Fehler ist aufgetreten: {str(e)}"}), 500
    return jsonify({"success": True, "message": "Zur Playlist hinzugefügt und Aktualisierung eingeplant."})

@playlist_bp.route('/playlist')
def playlists():
    device_config = current_app.config['DEVICE_CONFIG']
    playlist_manager = device_config.get_playlist_manager()
    refresh_info = device_config.get_refresh_info()

    return render_template(
        'playlist.html',
        playlist_config=playlist_manager.to_dict(),
        refresh_info=refresh_info.to_dict()
    )

@playlist_bp.route('/create_playlist', methods=['POST'])
def create_playlist():
    device_config = current_app.config['DEVICE_CONFIG']
    playlist_manager = device_config.get_playlist_manager()

    data = request.json
    playlist_name = data.get("playlist_name")
    start_time = data.get("start_time")
    end_time = data.get("end_time")

    if not playlist_name or not playlist_name.strip():
        return jsonify({"error": "Name der Playlist fehlt"}), 400
    if not start_time or not end_time:
        return jsonify({"error": "Start- und Endzeit fehlen"}), 400

    try:
        playlist = playlist_manager.get_playlist(playlist_name)
        if playlist:
            return jsonify({"error": f"Eine Playlist mit dem Namen '{playlist_name}' existiert bereits"}), 400

        result = playlist_manager.add_playlist(playlist_name, start_time, end_time)
        if not result:
            return jsonify({"error": "Playlist konnte nicht erstellt werden"}), 500

        # save changes to device config file
        device_config.write_config()

    except Exception as e:
        logger.exception("EXCEPTION CAUGHT: " + str(e))
        return jsonify({"error": f"Ein Fehler ist aufgetreten: {str(e)}"}), 500

    return jsonify({"success": True, "message": "Neue Playlist erstellt!"})


@playlist_bp.route('/update_playlist/<string:playlist_name>', methods=['PUT'])
def update_playlist(playlist_name):
    device_config = current_app.config['DEVICE_CONFIG']
    playlist_manager = device_config.get_playlist_manager()

    data = request.get_json()

    new_name = data.get("new_name")
    start_time = data.get("start_time")
    end_time = data.get("end_time")
    if not new_name or not start_time or not end_time:
        return jsonify({"success": False, "error": "Pflichtfelder fehlen"}), 400

    playlist = playlist_manager.get_playlist(playlist_name)
    if not playlist:
        return jsonify({"error": f"Playlist '{playlist_name}' existiert nicht"}), 400

    result = playlist_manager.update_playlist(playlist_name, new_name, start_time, end_time)
    if not result:
        return jsonify({"error": "Playlist konnte nicht aktualisiert werden"}), 500
    device_config.write_config()

    return jsonify({"success": True, "message": f"Playlist '{playlist_name}' aktualisiert!"})

@playlist_bp.route('/delete_playlist/<string:playlist_name>', methods=['DELETE'])
def delete_playlist(playlist_name):
    device_config = current_app.config['DEVICE_CONFIG']
    playlist_manager = device_config.get_playlist_manager()

    if not playlist_name:
        return jsonify({"error": f"Name der Playlist fehlt"}), 400

    playlist = playlist_manager.get_playlist(playlist_name)
    if not playlist:
        return jsonify({"error": f"Playlist '{playlist_name}' existiert nicht"}), 400

    # Delete all images associated with plugin instances in this playlist
    from blueprints.plugin import _delete_plugin_instance_images
    for plugin_instance in playlist.plugins:
        _delete_plugin_instance_images(device_config, plugin_instance)

    playlist_manager.delete_playlist(playlist_name)
    device_config.write_config()

    return jsonify({"success": True, "message": f"Playlist '{playlist_name}' gelöscht!"})

@playlist_bp.app_template_filter('format_relative_time')
def format_relative_time(iso_date_string):
    # Parse the input ISO date string
    dt = datetime.fromisoformat(iso_date_string)

    # Get the timezone from the parsed datetime
    if dt.tzinfo is None:
        raise ValueError("Input datetime doesn't have a timezone.")

    # Get the current time in the same timezone as the input datetime
    now = datetime.now(dt.tzinfo)
    delta = now - dt

    # Compute time difference
    diff_seconds = delta.total_seconds()
    diff_minutes = diff_seconds / 60

    # Define formatting
    time_format = "%H:%M"  # Example: 16:30
    month_day_format = "am %d.%m. um " + time_format  # Example: am 12.02. um 16:30

    # Determine relative time string
    if diff_seconds < 120:
        return "gerade eben"
    elif diff_minutes < 60:
        return f"vor {int(diff_minutes)} Minuten"
    elif dt.date() == now.date():
        return "heute um " + dt.strftime(time_format)
    elif dt.date() == (now.date() - timedelta(days=1)):
        return "gestern um " + dt.strftime(time_format)
    else:
        return dt.strftime(month_day_format)
