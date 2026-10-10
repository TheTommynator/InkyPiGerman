from flask import Blueprint, request, jsonify, current_app, render_template, send_from_directory
from plugins.plugin_registry import get_plugin_instance
from utils.app_utils import resolve_path, handle_request_files, parse_form
from refresh_task import ManualRefresh, PlaylistRefresh
import json
import os
import logging

logger = logging.getLogger(__name__)
plugin_bp = Blueprint("plugin", __name__)

# Das Bild ist fertig, der Bildaufbau auf dem E-Paper läuft danach im Hintergrund weiter
DISPLAY_STARTED_MESSAGE = "Bild erstellt – das Display wird jetzt aktualisiert. Den Fortschritt siehst du auf der Startseite."
DISPLAY_UNCHANGED_MESSAGE = "Das Display zeigt dieses Bild bereits."

def _display_message(display_started):
    return DISPLAY_STARTED_MESSAGE if display_started else DISPLAY_UNCHANGED_MESSAGE

def _delete_plugin_instance_images(device_config, plugin_instance_obj):
    """Delete all images associated with a plugin instance."""
    # Delete the plugin instance's generated image
    plugin_image_path = os.path.join(device_config.plugin_image_dir, plugin_instance_obj.get_image_path())
    if os.path.exists(plugin_image_path):
        try:
            os.remove(plugin_image_path)
            logger.info(f"Deleted plugin instance image: {plugin_image_path}")
        except Exception as e:
            logger.warning(f"Failed to delete plugin instance image {plugin_image_path}: {e}")

    # Call the plugin's cleanup method to handle plugin-specific resource cleanup
    try:
        plugin_config = device_config.get_plugin(plugin_instance_obj.plugin_id)
        if plugin_config:
            plugin = get_plugin_instance(plugin_config)
            plugin.cleanup(plugin_instance_obj.settings)
    except Exception as e:
        logger.warning(f"Error during plugin cleanup for {plugin_instance_obj.plugin_id}: {e}")

# Removed module-level PLUGINS_DIR - will resolve dynamically in route handlers

@plugin_bp.route('/plugin/<plugin_id>')
def plugin_page(plugin_id):
    device_config = current_app.config['DEVICE_CONFIG']
    playlist_manager = device_config.get_playlist_manager()

    # Find the plugin by id
    plugin_config = device_config.get_plugin(plugin_id)
    if plugin_config:
        try:
            plugin = get_plugin_instance(plugin_config)
            template_params = plugin.generate_settings_template()

            # retrieve plugin instance from the query parameters if updating existing plugin instance
            plugin_instance_name = request.args.get('instance')
            schedule_active = device_config.is_schedule_active()
            template_params["schedule_active"] = schedule_active
            if schedule_active:
                quiet = device_config.get_schedule().quiet
                template_params["morning_time"] = quiet.end if quiet.enabled else "06:00"
            view_id = request.args.get('ansicht')
            if view_id and schedule_active:
                # Einstellungen einer Ansicht aus dem neuen Zeitplan bearbeiten
                view = device_config.get_schedule().get_view(view_id)
                if not view or view.plugin_id != plugin_id:
                    return "Ansicht nicht gefunden", 404
                template_params["plugin_settings"] = view.settings
                template_params["view_id"] = view.id
                template_params["view_name"] = view.name
            elif plugin_instance_name:
                plugin_instance = playlist_manager.find_plugin(plugin_id, plugin_instance_name)
                if not plugin_instance:
                    return jsonify({"error": f"Plugin-Instanz {plugin_instance_name} existiert nicht"}), 500

                # add plugin instance settings to the template to prepopulate
                template_params["plugin_settings"] = plugin_instance.settings
                template_params["plugin_instance"] = plugin_instance_name

            template_params["playlists"] = playlist_manager.get_playlist_names()
        except Exception as e:
            logger.exception("EXCEPTION CAUGHT: " + str(e))
            return jsonify({"error": f"Ein Fehler ist aufgetreten: {str(e)}"}), 500
        return render_template('plugin.html', plugin=plugin_config, **template_params)
    else:
        return "Plugin nicht gefunden", 404

@plugin_bp.route('/images/<plugin_id>/<path:filename>')
def image(plugin_id, filename):
    # Resolve plugins directory dynamically
    plugins_dir = resolve_path("plugins")

    # Construct the full path to the plugin's file
    plugin_dir = os.path.join(plugins_dir, plugin_id)

    # Security check to prevent directory traversal
    safe_path = os.path.abspath(os.path.join(plugin_dir, filename))
    if not safe_path.startswith(os.path.abspath(plugin_dir)):
        return "Ungültiger Pfad", 403

    # Convert to absolute path for send_from_directory
    abs_plugin_dir = os.path.abspath(plugin_dir)

    # Check if the directory and file exist
    if not os.path.isdir(abs_plugin_dir):
        logger.error(f"Plugin directory not found: {abs_plugin_dir}")
        return "Plugin-Verzeichnis nicht gefunden", 404

    if not os.path.isfile(safe_path):
        logger.error(f"File not found: {safe_path}")
        return "Datei nicht gefunden", 404

    # Serve the file from the plugin directory
    return send_from_directory(abs_plugin_dir, filename)

@plugin_bp.route('/plugin_instance_image/<path:playlist_name>/<path:plugin_id>/<path:instance_name>')
def plugin_instance_image(playlist_name, plugin_id, instance_name):
    """Serve the generated image for a plugin instance."""
    device_config = current_app.config['DEVICE_CONFIG']
    playlist_manager = device_config.get_playlist_manager()

    # Find the plugin instance
    playlist = playlist_manager.get_playlist(playlist_name)
    if not playlist:
        return "Playlist nicht gefunden", 404

    plugin_instance = playlist.find_plugin(plugin_id, instance_name)
    if not plugin_instance:
        return "Plugin-Instanz nicht gefunden", 404

    # Get the image path
    image_filename = plugin_instance.get_image_path()
    image_path = os.path.join(device_config.plugin_image_dir, image_filename)

    # Check if the image exists
    if not os.path.exists(image_path):
        # Return a placeholder or 404
        return "Bild wurde noch nicht erzeugt", 404

    # Serve the image
    return send_from_directory(device_config.plugin_image_dir, image_filename)

@plugin_bp.route('/delete_plugin_instance', methods=['POST'])
def delete_plugin_instance():
    device_config = current_app.config['DEVICE_CONFIG']
    playlist_manager = device_config.get_playlist_manager()

    data = request.json
    playlist_name = data.get("playlist_name")
    plugin_id = data.get("plugin_id")
    plugin_instance = data.get("plugin_instance")

    try:
        playlist = playlist_manager.get_playlist(playlist_name)
        if not playlist:
            return jsonify({"success": False, "message": "Playlist nicht gefunden"}), 400

        # Get the plugin instance to find associated images
        plugin_instance_obj = playlist.find_plugin(plugin_id, plugin_instance)
        if not plugin_instance_obj:
            return jsonify({"success": False, "message": "Plugin-Instanz nicht gefunden"}), 400

        # Delete associated images before removing from playlist
        _delete_plugin_instance_images(device_config, plugin_instance_obj)

        result = playlist.delete_plugin(plugin_id, plugin_instance)
        if not result:
            return jsonify({"success": False, "message": "Plugin-Instanz nicht gefunden"}), 400

        # save changes to device config file
        device_config.write_config()

    except Exception as e:
        logger.exception("EXCEPTION CAUGHT: " + str(e))
        return jsonify({"error": f"Ein Fehler ist aufgetreten: {str(e)}"}), 500

    return jsonify({"success": True, "message": "Plugin-Instanz gelöscht."})

@plugin_bp.route('/update_plugin_instance/<string:instance_name>', methods=['PUT'])
def update_plugin_instance(instance_name):
    device_config = current_app.config['DEVICE_CONFIG']
    playlist_manager = device_config.get_playlist_manager()

    try:
        form_data = parse_form(request.form)

        if not instance_name:
            raise RuntimeError("Name der Instanz fehlt")
        plugin_settings = form_data
        plugin_settings.update(handle_request_files(request.files, request.form))

        plugin_id = plugin_settings.pop("plugin_id")
        plugin_instance = playlist_manager.find_plugin(plugin_id, instance_name)
        if not plugin_instance:
            return jsonify({"error": f"Plugin-Instanz {instance_name} existiert nicht"}), 500

        plugin_instance.settings = plugin_settings
        device_config.write_config()
    except Exception as e:
        return jsonify({"error": f"Ein Fehler ist aufgetreten: {str(e)}"}), 500
    return jsonify({"success": True, "message": f"Plugin-Instanz {instance_name} aktualisiert."})

@plugin_bp.route('/display_plugin_instance', methods=['POST'])
def display_plugin_instance():
    device_config = current_app.config['DEVICE_CONFIG']
    refresh_task = current_app.config['REFRESH_TASK']
    playlist_manager = device_config.get_playlist_manager()

    data = request.json
    playlist_name = data.get("playlist_name")
    plugin_id = data.get("plugin_id")
    plugin_instance_name = data.get("plugin_instance")

    try:
        playlist = playlist_manager.get_playlist(playlist_name)
        if not playlist:
            return jsonify({"success": False, "message": f"Playlist {playlist_name} nicht gefunden"}), 400

        plugin_instance = playlist.find_plugin(plugin_id, plugin_instance_name)
        if not plugin_instance:
            return jsonify({"success": False, "message": f"Plugin-Instanz '{plugin_instance_name}' nicht gefunden"}), 400

        display_started = refresh_task.manual_update(PlaylistRefresh(playlist, plugin_instance, force=True))
    except Exception as e:
        return jsonify({"error": f"Ein Fehler ist aufgetreten: {str(e)}"}), 500

    return jsonify({"success": True, "message": _display_message(display_started)}), 200

@plugin_bp.route('/update_now', methods=['POST'])
def update_now():
    device_config = current_app.config['DEVICE_CONFIG']
    refresh_task = current_app.config['REFRESH_TASK']
    display_manager = current_app.config['DISPLAY_MANAGER']

    try:
        plugin_settings = parse_form(request.form)
        plugin_settings.update(handle_request_files(request.files))
        plugin_id = plugin_settings.pop("plugin_id")

        # Check if refresh task is running
        if refresh_task.running:
            display_started = refresh_task.manual_update(ManualRefresh(plugin_id, plugin_settings))
            return jsonify({"success": True, "message": _display_message(display_started)}), 200
        else:
            # In development mode, directly update the display
            logger.info("Refresh task not running, updating display directly")
            plugin_config = device_config.get_plugin(plugin_id)
            if not plugin_config:
                return jsonify({"error": f"Plugin '{plugin_id}' nicht gefunden"}), 404

            plugin = get_plugin_instance(plugin_config)
            image = plugin.generate_image(plugin_settings, device_config)
            display_manager.display_image(image, image_settings=plugin_config.get("image_settings", []))

    except Exception as e:
        logger.exception(f"Error in update_now: {str(e)}")
        return jsonify({"error": f"Ein Fehler ist aufgetreten: {str(e)}"}), 500

    return jsonify({"success": True, "message": "Anzeige aktualisiert"}), 200
