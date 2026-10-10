"""Zugangsdaten: API-Schlüssel und Passwörter der Plugins über die Weboberfläche
setzen, statt die .env per SSH zu bearbeiten. Werte werden nur geschrieben,
nie an den Browser zurückgegeben."""

import logging

from flask import Blueprint, current_app, jsonify, render_template, request

from zugangsdaten import katalog_mit_status, pruefe

logger = logging.getLogger(__name__)
zugangsdaten_bp = Blueprint("zugangsdaten", __name__)


def _status(device_config):
    return katalog_mit_status(device_config.env_keys_set())


@zugangsdaten_bp.route("/zugangsdaten")
def zugangsdaten_page():
    device_config = current_app.config["DEVICE_CONFIG"]
    return render_template("zugangsdaten.html", gruppen=_status(device_config),
                           ziel=request.args.get("schluessel", ""))


@zugangsdaten_bp.route("/zugangsdaten/status")
def status():
    device_config = current_app.config["DEVICE_CONFIG"]
    return jsonify({s["key"]: s["gesetzt"] for g in _status(device_config) for s in g["schluessel"]})


@zugangsdaten_bp.route("/zugangsdaten", methods=["POST"])
def speichern():
    device_config = current_app.config["DEVICE_CONFIG"]
    daten = request.get_json(silent=True) or {}
    key = daten.get("key")
    wert = daten.get("wert", "")
    wert = wert.strip() if isinstance(wert, str) else wert

    fehler = pruefe(key, wert)
    if fehler:
        return jsonify({"error": fehler}), 400
    try:
        if wert:
            device_config.set_env_key(key, wert)
            meldung = "Gespeichert."
        else:
            device_config.remove_env_key(key)
            meldung = "Gelöscht."
    except OSError as e:
        logger.error(f"Zugangsdaten konnten nicht gespeichert werden: {e}")
        return jsonify({"error": f"Die .env konnte nicht geschrieben werden: {e}"}), 500
    logger.info(f"Zugangsdaten: {key} {'gesetzt' if wert else 'gelöscht'}")
    return jsonify({"success": True, "message": meldung, "gesetzt": bool(wert)})


@zugangsdaten_bp.route("/zugangsdaten/icloud/test", methods=["POST"])
def icloud_test():
    """Meldet sich mit den hinterlegten Daten bei iCloud an und listet die Kalender."""
    import requests
    from plugins.icloud_kalender.icloud_caldav import ICloudCalDAV

    device_config = current_app.config["DEVICE_CONFIG"]
    apple_id = device_config.load_env_key("ICLOUD_APPLE_ID")
    passwort = device_config.load_env_key("ICLOUD_APP_PASSWORT")
    if not apple_id or not passwort:
        return jsonify({"error": "Bitte zuerst Apple-ID und app-spezifisches Passwort hinterlegen."}), 400
    try:
        kalender = ICloudCalDAV(requests.Session(), apple_id.strip(), passwort.strip()).kalender()
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({
        "success": True,
        "message": f"Verbindung klappt – {len(kalender)} Kalender gefunden.",
        "kalender": [{"name": k["name"], "farbe": k["farbe"]} for k in kalender],
    })
