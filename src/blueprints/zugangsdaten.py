"""Zugangsdaten: API-Schlüssel und Passwörter der Plugins über die Weboberfläche
setzen, statt die .env per SSH zu bearbeiten. Werte werden nur geschrieben,
nie an den Browser zurückgegeben."""

import logging

from flask import Blueprint, current_app, jsonify, render_template, request

from zugangsdaten import ICLOUD_KONTEN, icloud_konten, katalog_mit_status, pruefe

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


def _icloud_kalender(konto):
    import requests
    from plugins.icloud_kalender.icloud_caldav import ICloudCalDAV

    kalender = ICloudCalDAV(requests.Session(), konto["apple_id"], konto["passwort"]).kalender()
    return [{"name": k["name"], "farbe": k["farbe"]} for k in kalender]


@zugangsdaten_bp.route("/zugangsdaten/icloud/test", methods=["POST"])
def icloud_test():
    """Meldet sich mit den hinterlegten Daten eines Kontos (?konto=1..3) bei iCloud an
    und listet dessen Kalender."""
    device_config = current_app.config["DEVICE_CONFIG"]
    nr = request.args.get("konto", "1")
    if not nr.isdigit() or not 1 <= int(nr) <= ICLOUD_KONTEN:
        return jsonify({"error": "Unbekanntes iCloud-Konto"}), 400
    konto = next((k for k in icloud_konten(device_config.load_env_key) if k["nr"] == int(nr)), None)
    if not konto:
        return jsonify({"error": "Bitte zuerst Apple-ID und app-spezifisches Passwort hinterlegen."}), 400
    try:
        kalender = _icloud_kalender(konto)
    except Exception as e:
        return jsonify({"error": str(e)}), 502
    return jsonify({
        "success": True,
        "message": f"Verbindung klappt – {len(kalender)} Kalender gefunden.",
        "kalender": kalender,
    })


@zugangsdaten_bp.route("/zugangsdaten/icloud/kalender", methods=["POST"])
def icloud_alle_kalender():
    """Kalender aller hinterlegten iCloud-Konten, für die Auswahl im Plugin.
    Ein fehlerhaftes Konto liefert seine Fehlermeldung, die anderen trotzdem ihre Kalender."""
    device_config = current_app.config["DEVICE_CONFIG"]
    konten = icloud_konten(device_config.load_env_key)
    if not konten:
        return jsonify({"error": "Bitte zuerst Apple-ID und app-spezifisches Passwort hinterlegen."}), 400
    antwort = []
    for konto in konten:
        eintrag = {"nr": konto["nr"], "name": konto["name"], "kalender": []}
        try:
            eintrag["kalender"] = _icloud_kalender(konto)
        except Exception as e:
            eintrag["error"] = str(e)
        antwort.append(eintrag)
    return jsonify({"success": True, "konten": antwort})
