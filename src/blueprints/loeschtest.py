"""Löschtest: zeigt alltagsnahe Bildwechsel ohne Löschen und schlägt danach die
Schwelle für „Altes Bild löschen: Automatisch“ vor.

Die Szenen und die Auswertung stehen in utils/loeschtest.py.
"""

import logging
import os
import shutil

from flask import Blueprint, current_app, jsonify, render_template, request
from PIL import Image

from display import loeschen
from refresh_task import ImageRefresh
from utils import loeschtest
from utils.app_utils import resolve_path

logger = logging.getLogger(__name__)
loeschtest_bp = Blueprint("loeschtest", __name__)

SNAPSHOT_FILE = os.path.join("static", "images", "loeschtest_snapshot.png")
# Was vor dem Test angezeigt wurde, um es am Ende wiederherzustellen
_vorher = {"refresh_info": None}


def _snapshot_path():
    return resolve_path(SNAPSHOT_FILE)


def _groesse(device_config):
    try:
        width, height = device_config.get_resolution()
    except (TypeError, ValueError):
        width, height = 800, 480
    if device_config.get_config("orientation") == "vertical":
        width, height = height, width
    return int(width), int(height)


def _show(image, title, clear, hold=True, refresh_info=None):
    """Schickt ein fertiges Bild ans Display, mit vorgegebenem Löschen (None = Einstellung)."""
    refresh_task = current_app.config['REFRESH_TASK']
    if refresh_task.running:
        return refresh_task.manual_update(ImageRefresh(image, title, clear=clear, hold=hold,
                                                       refresh_info=refresh_info, always_show=True))
    current_app.config['DISPLAY_MANAGER'].display_image(image, ["skip-enhancement"], title=title, clear=clear)
    return True


def _error(message, status=400):
    return jsonify({"error": message}), status


@loeschtest_bp.route('/settings/loeschtest')
def loeschtest_page():
    device_config = current_app.config['DEVICE_CONFIG']
    szenen = [{key: s[key] for key in ("id", "name", "beschreibung", "hinweis")} for s in loeschtest.SZENEN]
    return render_template('loeschtest.html', szenen=szenen,
                           modus=loeschen.modus(device_config), schwelle=loeschen.schwelle(device_config))


@loeschtest_bp.route('/settings/loeschtest/start', methods=['POST'])
def loeschtest_start():
    """Merkt sich das aktuelle Display-Bild für die Rückkehr am Ende."""
    device_config = current_app.config['DEVICE_CONFIG']
    current_image = device_config.current_image_file
    info = device_config.get_refresh_info()
    # Zeigt das Display schon ein Testbild (Test neu gestartet), das alte Bild behalten
    if os.path.isfile(current_image) and getattr(info, "plugin_id", None) != "loeschtest":
        os.makedirs(os.path.dirname(_snapshot_path()), exist_ok=True)
        shutil.copyfile(current_image, _snapshot_path())
        gemerkt = {key: value for key, value in vars(info).items()
                   if key not in ("refresh_time", "image_hash") and value is not None}
        _vorher["refresh_info"] = gemerkt if gemerkt.get("refresh_type") and gemerkt.get("plugin_id") else None
    return jsonify({"success": True})


@loeschtest_bp.route('/settings/loeschtest/zeigen', methods=['POST'])
def loeschtest_zeigen():
    """Zeigt das Ausgangsbild einer Szene (mit Löschen) oder das Folgebild (ohne Löschen)."""
    data = request.get_json(silent=True) or {}
    teil = data.get("bild")
    if teil not in ("vorher", "nachher"):
        return _error("Unbekanntes Bild.")
    try:
        s = loeschtest.szene(data.get("szene"))
    except ValueError as e:
        return _error(str(e))

    device_config = current_app.config['DEVICE_CONFIG']
    vorher, nachher = loeschtest.bilder(s["id"], _groesse(device_config))
    anteil = loeschen.anteil_geaendert(loeschen.pigment_bild(vorher), loeschen.pigment_bild(nachher))
    try:
        if teil == "vorher":
            _show(vorher, f"Löschtest: {s['name']} (Ausgangsbild)", clear=True)
        else:
            _show(nachher, f"Löschtest: {s['name']} (ohne Löschen)", clear=False)
    except Exception as e:
        logger.exception("Löschtest: Anzeige fehlgeschlagen")
        return _error(f"Das Testbild konnte nicht angezeigt werden: {e}", 500)
    return jsonify({"success": True, "anteil": round(anteil * 100, 1)})


@loeschtest_bp.route('/settings/loeschtest/auswerten', methods=['POST'])
def loeschtest_auswerten():
    data = request.get_json(silent=True) or {}
    ergebnisse = []
    for eintrag in data.get("ergebnisse") or []:
        try:
            ergebnisse.append({"anteil": float(eintrag["anteil"]), "bewertung": str(eintrag["bewertung"])})
        except (KeyError, TypeError, ValueError):
            return _error("Ungültige Ergebnisse.")
    empfehlung = loeschtest.empfehlung(ergebnisse)
    if empfehlung is None:
        return _error("Bewerte mindestens eine Szene.")
    return jsonify({"success": True, "empfehlung": empfehlung})


@loeschtest_bp.route('/settings/loeschtest/ende', methods=['POST'])
def loeschtest_ende():
    """Zeigt wieder das Bild von vor dem Test; danach läuft der Zeitplan normal weiter."""
    if not os.path.isfile(_snapshot_path()):
        return jsonify({"success": True, "restored": False})
    try:
        with Image.open(_snapshot_path()) as img:
            image = img.convert("RGB")
        info = _vorher["refresh_info"]
        _show(image, (info or {}).get("plugin_instance") or "Vorheriges Bild", clear=None, hold=False,
              refresh_info=info)
    except Exception as e:
        logger.exception("Löschtest: vorheriges Bild konnte nicht angezeigt werden")
        return _error(f"Das vorherige Bild konnte nicht angezeigt werden: {e}", 500)
    return jsonify({"success": True, "restored": True})
