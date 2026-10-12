import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

for module in ("flask", "dotenv", "PIL", "psutil", "pytz"):
    pytest.importorskip(module)

import flask  # noqa: E402
from config import Config  # noqa: E402
from model import RefreshInfo  # noqa: E402
from blueprints.ansichten import ansichten_bp  # noqa: E402
from blueprints.calibration import calibration_bp  # noqa: E402
from blueprints.main import main_bp  # noqa: E402
from blueprints.plugin import plugin_bp  # noqa: E402
from blueprints.settings import settings_bp  # noqa: E402
from blueprints.updates import updates_bp  # noqa: E402
from blueprints.zugangsdaten import zugangsdaten_bp  # noqa: E402
from blueprints.loeschtest import loeschtest_bp  # noqa: E402


class FakeRefreshTask:
    running = True

    def __init__(self):
        self.signals = 0
        self.shown = []

    def manual_update(self, action):
        self.shown.append(action)
        return True

    def signal_config_change(self):
        self.signals += 1


@pytest.fixture
def env(tmp_path):
    path = tmp_path / "device.json"
    path.write_text(json.dumps({"name": "InkyPi", "orientation": "horizontal", "timezone": "Europe/Berlin",
                                "time_format": "24h", "image_settings": {"saturation": 1.4}}))
    config = Config.__new__(Config)
    config.config_file = str(path)
    config.config = config.read_config()
    config.playlist_manager = config.load_playlist_manager()
    config.refresh_info = RefreshInfo.from_dict({})
    config._schedule = None

    app = flask.Flask(__name__, template_folder=str(Path(__file__).resolve().parent.parent / "src" / "templates"))
    for bp in (settings_bp, main_bp, ansichten_bp, plugin_bp, updates_bp, zugangsdaten_bp, calibration_bp, loeschtest_bp):
        app.register_blueprint(bp)
    task = FakeRefreshTask()
    app.config.update(DEVICE_CONFIG=config, REFRESH_TASK=task)
    return app.test_client(), path, task


def saved(path):
    return json.loads(path.read_text())


def test_einzelne_einstellung_wird_sofort_gespeichert(env):
    client, path, task = env
    response = client.post("/settings/geraet", json={"orientation": "vertical"})
    assert response.status_code == 200
    assert saved(path)["orientation"] == "vertical"
    assert saved(path)["name"] == "InkyPi"
    assert task.signals == 0

    client.post("/settings/geraet", json={"inverted_image": True, "log_system_stats": False})
    assert saved(path)["inverted_image"] is True and saved(path)["log_system_stats"] is False

    client.post("/settings/geraet", json={"display_clear_mode": "automatisch", "display_clear_threshold": 45,
                                                "display_clear_max_updates": 12})
    assert saved(path)["display_clear_mode"] == "automatisch"
    assert saved(path)["display_clear_threshold"] == 45
    assert saved(path)["display_clear_max_updates"] == 12


def test_zeitzone_weckt_den_zeitplan(env):
    client, path, task = env
    assert client.post("/settings/geraet", json={"timezone": "Europe/Berlin"}).status_code == 200
    assert task.signals == 0
    assert client.post("/settings/geraet", json={"timezone": "America/New_York"}).status_code == 200
    assert saved(path)["timezone"] == "America/New_York"
    assert task.signals == 1


@pytest.mark.parametrize("data, text", [
    ({"name": "   "}, "Namen"),
    ({"name": "x" * 41}, "höchstens"),
    ({"orientation": "schief"}, "Ausrichtung"),
    ({"time_format": "13h"}, "Zeitformat"),
    ({"display_clear_mode": "manchmal"}, "Löschen"),
    ({"display_clear_threshold": 2}, "zwischen 5 und 100"),
    ({"display_clear_threshold": "viel"}, "ganze Zahl"),
    ({"display_clear_max_updates": 0}, "zwischen 1 und 500"),
    ({"timezone": "Mond/Krater"}, "keine bekannte Zeitzone"),
    ({}, "Keine Einstellung"),
])
def test_ungueltige_werte_werden_abgelehnt(env, data, text):
    client, path, _ = env
    before = saved(path)
    response = client.post("/settings/geraet", json=data)
    assert response.status_code == 400
    assert text in response.get_json()["error"]
    assert saved(path) == before


def test_name_wird_bereinigt(env):
    client, path, _ = env
    client.post("/settings/geraet", json={"name": "  Wohnzimmer  "})
    assert saved(path)["name"] == "Wohnzimmer"


@pytest.mark.parametrize("url, text", [
    ("/settings", "Software-Update"),
    ("/settings/geraet", "Zeitzone"),
    ("/settings/bild", "1.40"),
    ("/settings/updates", "Jetzt aktualisieren"),
    ("/settings/loeschtest", "Test starten"),
])
def test_seiten_werden_angezeigt(env, url, text):
    client, _, _ = env
    response = client.get(url)
    assert response.status_code == 200
    assert text in response.get_data(as_text=True)


def test_loeschtest_zeigt_ablauf_erst_sauber_dann_ohne_loeschen(env):
    client, _, task = env
    first = client.post("/settings/loeschtest/zeigen", json={"ablauf": "tag", "schritt": 0}).get_json()
    assert (first["bilder"], first["flaeche"]) == (0, 0.0)
    second = client.post("/settings/loeschtest/zeigen", json={"ablauf": "tag", "schritt": 2}).get_json()
    assert second["bilder"] == 2 and second["flaeche"] > 5
    assert [action.clear for action in task.shown] == [True, False]
    assert all(action.always_show for action in task.shown)

    assert client.post("/settings/loeschtest/zeigen", json={"ablauf": "mond", "schritt": 0}).status_code == 400
    assert client.post("/settings/loeschtest/zeigen", json={"ablauf": "tag", "schritt": 99}).status_code == 400


def test_loeschtest_auswertung(env):
    client, _, _ = env
    response = client.post("/settings/loeschtest/auswerten", json={"ergebnisse": [
        {"ablauf": "uhr", "bilder": 1, "flaeche": 3, "bewertung": "sauber"},
        {"ablauf": "uhr", "bilder": 2, "flaeche": 4, "bewertung": "stoerend"}]})
    empfehlung = response.get_json()["empfehlung"]
    assert empfehlung["modus"] == "automatisch" and empfehlung["max_bilder"] == 1
    assert client.post("/settings/loeschtest/auswerten", json={"ergebnisse": []}).status_code == 400
