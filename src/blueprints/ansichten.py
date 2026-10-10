"""Seite „Ansichten“ und API für den neuen Zeitplan (Beta)."""

import logging
import os
from datetime import date, datetime, timedelta

from flask import Blueprint, current_app, jsonify, render_template, request, send_from_directory, url_for

from refresh_task import ViewRefresh
from utils.app_utils import handle_request_files, parse_form
from zeitplan import Override, View, parse_hm
from zeitplan_bearbeiten import (
    ScheduleError, apply_update, check_view_name, day_plan_for_page, new_id, schedule_for_page,
)
from zeitplaner import AUTO_REFRESH_MINUTES, DEFAULT_AUTO_REFRESH_MINUTES

logger = logging.getLogger(__name__)
ansichten_bp = Blueprint("ansichten", __name__)

INACTIVE_ERROR = "Der neue Zeitplan ist ausgeschaltet. Du kannst ihn in den Einstellungen einschalten."


def _deps():
    return current_app.config["DEVICE_CONFIG"], current_app.config["REFRESH_TASK"]


def _now(refresh_task):
    """Aktuelle Ortszeit des Geräts als naive datetime (wie im Zeitplaner)."""
    return refresh_task._get_current_datetime().replace(tzinfo=None, second=0, microsecond=0)


def _save(device_config, refresh_task, schedule):
    """Speichert den Zeitplan und weckt den Hintergrund-Task, damit er neu plant."""
    with refresh_task.condition:
        device_config.save_schedule(schedule)
    refresh_task.signal_config_change()


def _error(message, status=400):
    return jsonify({"success": False, "error": message}), status


def _require_active(device_config):
    if not device_config.is_schedule_active():
        return _error(INACTIVE_ERROR, 409)
    return None


def _plugin_list(device_config):
    plugins = []
    for plugin in device_config.get_plugins():
        plugins.append({
            "id": plugin["id"],
            "name": plugin.get("display_name", plugin["id"]),
            "icon": url_for("plugin.image", plugin_id=plugin["id"], filename="icon.png"),
            "auto_refresh_minutes": AUTO_REFRESH_MINUTES.get(plugin["id"], DEFAULT_AUTO_REFRESH_MINUTES),
        })
    return plugins


def page_data(device_config, open_view=""):
    """Daten für ansichten.js (Seite „Ansichten“ und Tagesplan auf der Startseite)."""
    active = device_config.is_schedule_active()
    return {
        "active": active,
        "schedule": schedule_for_page(device_config.get_schedule()) if active else None,
        "plugins": _plugin_list(device_config),
        "openView": open_view,
        "urls": {
            "beta": url_for("ansichten.set_beta"),
            "schedule": url_for("ansichten.update_schedule"),
            "override": url_for("ansichten.end_override"),
            "day": url_for("ansichten.day_plan"),
            "ansichten": url_for("ansichten.ansichten_page"),
            "view": "/api/ansicht/",
            "plugin": "/plugin/",
        },
    }


@ansichten_bp.route("/ansichten")
def ansichten_page():
    device_config, _ = _deps()
    return render_template(
        "ansichten.html",
        active=device_config.is_schedule_active(),
        zdata=page_data(device_config, request.args.get("ansicht", "")),
    )


@ansichten_bp.route("/api/zeitplan/beta", methods=["POST"])
def set_beta():
    device_config, refresh_task = _deps()
    enabled = bool((request.get_json(silent=True) or {}).get("enabled"))
    try:
        with refresh_task.condition:
            device_config.set_schedule_active(enabled)
        refresh_task.signal_config_change()
    except Exception as e:
        logger.exception("Zeitplan konnte nicht umgeschaltet werden")
        return _error(f"Ein Fehler ist aufgetreten: {e}", 500)
    if enabled:
        message = "Der neue Zeitplan ist eingeschaltet. Deine Playlists wurden als Ansichten übernommen."
    else:
        message = "Der neue Zeitplan ist ausgeschaltet. Es gelten wieder die Playlists."
    return jsonify({"success": True, "enabled": enabled, "message": message})


@ansichten_bp.route("/api/zeitplan", methods=["PUT"])
def update_schedule():
    device_config, refresh_task = _deps()
    inactive = _require_active(device_config)
    if inactive:
        return inactive
    try:
        schedule, renames = apply_update(device_config.get_schedule(), request.get_json(silent=True) or {})
    except ScheduleError as e:
        return _error(str(e))

    for old, new in renames:
        old_path = os.path.join(device_config.plugin_image_dir, old)
        if os.path.exists(old_path):
            try:
                os.replace(old_path, os.path.join(device_config.plugin_image_dir, new))
            except OSError:
                logger.warning(f"Bild {old} konnte nicht umbenannt werden")
    _save(device_config, refresh_task, schedule)
    return jsonify({"success": True, "message": "Gesichert.", "schedule": schedule_for_page(schedule)})


@ansichten_bp.route("/api/ansicht", methods=["POST"])
def create_view():
    """Neue Ansicht aus der Plugin-Seite (Formular mit den Plugin-Einstellungen)."""
    device_config, refresh_task = _deps()
    inactive = _require_active(device_config)
    if inactive:
        return inactive
    try:
        settings = parse_form(request.form)
        plugin_id = settings.pop("plugin_id", None)
        name = settings.pop("view_name", None)
        if not plugin_id or not device_config.get_plugin(plugin_id):
            return _error("Unbekanntes Plugin.")
        schedule = device_config.get_schedule()
        name = check_view_name(name, schedule)
        settings.update(handle_request_files(request.files))
        view = View(new_id("v"), plugin_id, name, settings=settings,
                    duration_minutes=schedule.default_duration_minutes)
        schedule.views.append(view)
        _save(device_config, refresh_task, schedule)
    except ScheduleError as e:
        return _error(str(e))
    except Exception as e:
        logger.exception("Ansicht konnte nicht angelegt werden")
        return _error(f"Ein Fehler ist aufgetreten: {e}", 500)
    return jsonify({
        "success": True,
        "message": f"Ansicht „{name}“ hinzugefügt. Sie läuft jetzt in der Rotation.",
        "url": url_for("ansichten.ansichten_page", ansicht=view.id),
    })


@ansichten_bp.route("/api/ansicht/<view_id>/einstellungen", methods=["PUT"])
def update_view_settings(view_id):
    """Plugin-Einstellungen einer Ansicht ändern (aus der Plugin-Seite)."""
    device_config, refresh_task = _deps()
    inactive = _require_active(device_config)
    if inactive:
        return inactive
    schedule = device_config.get_schedule()
    view = schedule.get_view(view_id)
    if not view:
        return _error("Diese Ansicht gibt es nicht mehr.", 404)
    try:
        settings = parse_form(request.form)
        settings.update(handle_request_files(request.files, request.form))
        settings.pop("plugin_id", None)
        settings.pop("view_name", None)
        view.settings = settings
        view.latest_refresh_time = None  # beim nächsten Anzeigen neu erzeugen
        _save(device_config, refresh_task, schedule)
    except Exception as e:
        logger.exception("Einstellungen der Ansicht konnten nicht gespeichert werden")
        return _error(f"Ein Fehler ist aufgetreten: {e}", 500)
    return jsonify({"success": True, "message": f"Einstellungen von „{view.name}“ gesichert."})


@ansichten_bp.route("/api/ansicht/<view_id>", methods=["DELETE"])
def delete_view(view_id):
    device_config, refresh_task = _deps()
    inactive = _require_active(device_config)
    if inactive:
        return inactive
    schedule = device_config.get_schedule()
    view = schedule.get_view(view_id)
    if not view:
        return _error("Diese Ansicht gibt es nicht mehr.", 404)

    from blueprints.plugin import _delete_plugin_instance_images
    _delete_plugin_instance_images(device_config, view)
    schedule.views = [v for v in schedule.views if v.id != view_id]
    if schedule.override and schedule.override.view_id == view_id:
        schedule.override = None
    _save(device_config, refresh_task, schedule)
    return jsonify({"success": True, "message": f"„{view.name}“ gelöscht."})


@ansichten_bp.route("/api/ansicht/<view_id>/anzeigen", methods=["POST"])
def show_view(view_id):
    """„Jetzt anzeigen“: für 1 Stunde, bis morgen früh oder bis zur nächsten Änderung."""
    device_config, refresh_task = _deps()
    inactive = _require_active(device_config)
    if inactive:
        return inactive
    schedule = device_config.get_schedule()
    view = schedule.get_view(view_id)
    if not view:
        return _error("Diese Ansicht gibt es nicht mehr.", 404)

    duration = (request.get_json(silent=True) or {}).get("bis", "1h")
    now = _now(refresh_task)
    if duration == "1h":
        until = now + timedelta(hours=1)
    elif duration == "morgen":
        morning = parse_hm(schedule.quiet.end if schedule.quiet.enabled else "06:00")
        until = datetime.combine(now.date() + timedelta(days=1), datetime.min.time()) + timedelta(minutes=morning)
    elif duration == "immer":
        until = None
    else:
        return _error("Unbekannte Dauer.")

    previous = schedule.override
    schedule.override = Override(view.id, now.isoformat(), until.isoformat() if until else None)
    with refresh_task.condition:
        device_config.save_schedule(schedule)
    try:
        display_started = refresh_task.manual_update(ViewRefresh(view))
    except Exception as e:
        logger.exception("Ansicht konnte nicht angezeigt werden")
        # nichts angezeigt: es geht weiter wie vorher
        schedule.override = previous
        _save(device_config, refresh_task, schedule)
        return _error(f"Die Ansicht konnte nicht erzeugt werden: {e}", 500)
    if display_started is False:
        message = f"„{view.name}“ ist schon zu sehen."
    else:
        message = f"„{view.name}“ wird jetzt angezeigt. Den Fortschritt siehst du auf der Startseite."
    return jsonify({"success": True, "message": message, "override": schedule.override.to_dict()})


@ansichten_bp.route("/api/zeitplan/manuell", methods=["DELETE"])
def end_override():
    device_config, refresh_task = _deps()
    inactive = _require_active(device_config)
    if inactive:
        return inactive
    schedule = device_config.get_schedule()
    schedule.override = None
    _save(device_config, refresh_task, schedule)
    return jsonify({"success": True, "message": "Es geht wieder nach Zeitplan weiter."})


@ansichten_bp.route("/api/zeitplan/tag")
def day_plan():
    """Tagesplan für die Startseite (?datum=JJJJ-MM-TT, sonst heute)."""
    device_config, refresh_task = _deps()
    inactive = _require_active(device_config)
    if inactive:
        return inactive
    now = _now(refresh_task)
    try:
        day = date.fromisoformat(request.args["datum"]) if request.args.get("datum") else now.date()
    except ValueError:
        return _error("Ungültiges Datum.")
    response = jsonify(day_plan_for_page(device_config.get_schedule(), day, now))
    response.headers["Cache-Control"] = "no-store"
    return response


@ansichten_bp.route("/api/ansicht/<view_id>/bild")
def view_image(view_id):
    device_config, _ = _deps()
    view = device_config.get_schedule().get_view(view_id)
    if not view:
        return "Ansicht nicht gefunden", 404
    path = os.path.join(device_config.plugin_image_dir, view.get_image_path())
    if not os.path.exists(path):
        return "Bild wurde noch nicht erzeugt", 404
    response = send_from_directory(device_config.plugin_image_dir, view.get_image_path())
    response.headers["Cache-Control"] = "no-cache"
    return response
