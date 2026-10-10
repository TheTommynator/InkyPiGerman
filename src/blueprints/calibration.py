"""Bild-Assistent: führt Schritt für Schritt zu den passenden Bildeinstellungen.

Die Testbilder erzeugt das Plugin "Bildkalibrierung"; dieser Blueprint
berechnet die Stufen jeder Runde und schickt die Bilder ans Display.
"""

import logging
import os
import shutil
import string

from flask import Blueprint, current_app, jsonify, render_template, request

from plugins.plugin_registry import get_plugin_instance
from refresh_task import ManualRefresh
from utils.app_utils import resolve_path
from utils import calibration_wizard as wizard

logger = logging.getLogger(__name__)
calibration_bp = Blueprint("calibration", __name__)

PLUGIN_ID = "image_calibration"
SNAPSHOT_FILE = os.path.join("static", "images", "calibration_snapshot.png")


def _snapshot_path():
    return resolve_path(SNAPSHOT_FILE)


def _current_values():
    device_config = current_app.config['DEVICE_CONFIG']
    current = device_config.get_config("image_settings", default={}) or {}
    return {key: wizard.clamp(current.get(key, 1.0)) for key in wizard.STEP_IDS}


def _read_values(data, key="base"):
    raw = data.get(key)
    if not isinstance(raw, dict):
        raise ValueError("Bildwerte fehlen.")
    try:
        return {step: wizard.clamp(raw.get(step, 1.0)) for step in wizard.STEP_IDS}
    except (TypeError, ValueError):
        raise ValueError("Ungültige Bildwerte.")


def _source_settings(motif):
    """Motiv für das Plugin: Testbild oder das gemerkte aktuelle Bild."""
    if motif == "current" and os.path.isfile(_snapshot_path()):
        return {"source": "upload", "calibrationImage": _snapshot_path()}
    return {"source": "pattern"}


def _show(settings):
    """Erzeugt das Bild über das Plugin und schickt es ans Display."""
    device_config = current_app.config['DEVICE_CONFIG']
    plugin_config = device_config.get_plugin(PLUGIN_ID)
    if not plugin_config:
        raise RuntimeError("Das Plugin „Bildkalibrierung“ ist nicht installiert.")

    refresh_task = current_app.config['REFRESH_TASK']
    if refresh_task.running:
        refresh_task.manual_update(ManualRefresh(PLUGIN_ID, settings))
    else:
        plugin = get_plugin_instance(plugin_config)
        image = plugin.generate_image(settings, device_config)
        current_app.config['DISPLAY_MANAGER'].display_image(
            image, image_settings=plugin_config.get("image_settings", []))


def _error(message, status=400):
    return jsonify({"error": message}), status


@calibration_bp.route('/bildassistent')
def wizard_page():
    return render_template(
        'calibration.html',
        steps=wizard.STEPS,
        current_values=_current_values(),
        has_current_image=os.path.isfile(current_app.config['DEVICE_CONFIG'].current_image_file),
    )


@calibration_bp.route('/bildassistent/start', methods=['POST'])
def wizard_start():
    """Merkt sich das aktuelle Display-Bild, als Motiv und für die Rückkehr am Ende."""
    device_config = current_app.config['DEVICE_CONFIG']
    current_image = device_config.current_image_file
    last_plugin = getattr(device_config.get_refresh_info(), "plugin_id", None)
    snapshot = _snapshot_path()

    # Zeigt das Display schon ein Testbild (Assistent neu gestartet), das alte Bild behalten
    if os.path.isfile(current_image) and (last_plugin != PLUGIN_ID or not os.path.isfile(snapshot)):
        os.makedirs(os.path.dirname(snapshot), exist_ok=True)
        shutil.copyfile(current_image, snapshot)

    return jsonify({"success": True, "has_snapshot": os.path.isfile(snapshot), "values": _current_values()})


@calibration_bp.route('/bildassistent/runde', methods=['POST'])
def wizard_round():
    """Zeigt eine Runde an: erste grobe Stufen oder feinere um den gewählten Wert."""
    data = request.get_json(silent=True) or {}
    step_id = data.get("step")
    if step_id not in wizard.STEP_IDS:
        return _error("Unbekannter Schritt.")

    try:
        base = _read_values(data)
        previous = data.get("previous")
        if previous:
            values = wizard.refine([wizard.clamp(v) for v in previous], wizard.clamp(data.get("picked")))
            if values is None:
                return _error("Feiner geht es nicht mehr.")
        else:
            values = wizard.first_round(step_id)
    except (TypeError, ValueError) as e:
        return _error(str(e))

    index = wizard.STEP_IDS.index(step_id)
    name = wizard.STEPS[index]["name"]
    tiles = []
    for i, value in enumerate(values):
        tile_values = dict(base)
        tile_values[step_id] = value
        tiles.append({"label": f"{string.ascii_uppercase[i]}   {name} {value:.2f}", "values": tile_values})

    settings = {
        "mode": "wizard",
        "tiles": tiles,
        "footer": f"Bild-Assistent · Schritt {index + 1} von {len(wizard.STEPS)}: {name} – "
                  f"wähle im Browser die schönste Kachel",
        **_source_settings(data.get("motif")),
    }
    try:
        _show(settings)
    except Exception as e:
        logger.exception("Bild-Assistent: Anzeige fehlgeschlagen")
        return _error(f"Das Testbild konnte nicht angezeigt werden: {e}", 500)

    return jsonify({"success": True, "values": values, "finest": wizard.is_finest(values)})


@calibration_bp.route('/bildassistent/vergleich', methods=['POST'])
def wizard_compare():
    """Zeigt vorher und nachher nebeneinander."""
    data = request.get_json(silent=True) or {}
    try:
        before = _read_values(data, "before")
        after = _read_values(data, "after")
    except ValueError as e:
        return _error(str(e))

    settings = {
        "mode": "wizard",
        "tiles": [{"label": "Vorher", "values": before}, {"label": "Nachher", "values": after}],
        "footer": "Bild-Assistent · Vorher und nachher im Vergleich",
        **_source_settings(data.get("motif")),
    }
    try:
        _show(settings)
    except Exception as e:
        logger.exception("Bild-Assistent: Vergleich fehlgeschlagen")
        return _error(f"Der Vergleich konnte nicht angezeigt werden: {e}", 500)
    return jsonify({"success": True})


@calibration_bp.route('/bildassistent/fertig', methods=['POST'])
def wizard_finish():
    """Zeigt das Bild von vor dem Assistenten wieder an, mit den gespeicherten Werten."""
    if not os.path.isfile(_snapshot_path()):
        return jsonify({"success": True, "restored": False})

    settings = {"mode": "fullscreen", "values": _current_values(), **_source_settings("current")}
    try:
        _show(settings)
    except Exception as e:
        logger.exception("Bild-Assistent: vorheriges Bild konnte nicht angezeigt werden")
        return _error(f"Das vorherige Bild konnte nicht angezeigt werden: {e}", 500)
    return jsonify({"success": True, "restored": True})
