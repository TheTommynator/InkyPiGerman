import json
import sys
import threading
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

for module in ("flask", "dotenv", "PIL", "psutil", "pytz"):
    pytest.importorskip(module)

import flask  # noqa: E402
from config import Config  # noqa: E402
from model import RefreshInfo  # noqa: E402
from blueprints import ansichten  # noqa: E402
from blueprints.plugin import plugin_bp  # noqa: E402

JETZT = datetime(2026, 10, 10, 8, 5)


def playlist_plugin(plugin_id, name):
    return {"plugin_id": plugin_id, "name": name, "plugin_settings": {"stadt": "Berlin"},
            "refresh": {"interval": 1800}, "latest_refresh_time": None}


class FakeRefreshTask:
    def __init__(self):
        self.condition = threading.Condition()
        self.signals = 0
        self.shown = []

    def signal_config_change(self):
        self.signals += 1

    def manual_update(self, action):
        if getattr(self, "fail", False):
            raise RuntimeError("Plugin kaputt")
        self.shown.append(action)
        return True

    def _get_current_datetime(self):
        return JETZT


@pytest.fixture
def env(tmp_path):
    device = {
        "name": "InkyPi",
        "plugin_cycle_interval_seconds": 600,
        "playlist_config": {"playlists": [
            {"name": "Default", "start_time": "00:00", "end_time": "24:00", "plugins": [playlist_plugin("weather", "Wetter")]},
        ], "active_playlist": None},
        "refresh_info": {},
    }
    path = tmp_path / "device.json"
    path.write_text(json.dumps(device))
    config = Config.__new__(Config)
    config.config_file = str(path)
    config.plugin_image_dir = str(tmp_path)
    config.config = config.read_config()
    config.plugins_list = [{"id": "weather", "display_name": "Wetter"}, {"id": "clock", "display_name": "Uhr"}]
    config.playlist_manager = config.load_playlist_manager()
    config.refresh_info = RefreshInfo.from_dict({})
    config._schedule = None

    app = flask.Flask(__name__, template_folder=str(Path(__file__).resolve().parent.parent / "src" / "templates"))
    app.register_blueprint(ansichten.ansichten_bp)
    app.register_blueprint(plugin_bp)
    task = FakeRefreshTask()
    app.config.update(DEVICE_CONFIG=config, REFRESH_TASK=task)
    return app.test_client(), config, task, path


def einschalten(client):
    return client.post("/api/zeitplan/beta", json={"enabled": True})


def test_ausgeschaltet_sind_aenderungen_gesperrt(env):
    client, config, _, path = env
    assert client.put("/api/zeitplan", json={"views": []}).status_code == 409
    assert "schedule" not in json.loads(path.read_text())


def test_einschalten_uebernimmt_playlists_und_sichert(env):
    client, config, task, path = env
    response = einschalten(client)
    assert response.status_code == 200
    saved = json.loads(path.read_text())
    assert saved["zeitplan_beta"] is True
    assert [v["name"] for v in saved["schedule"]["views"]] == ["Wetter"]
    assert saved["playlist_config"]["playlists"][0]["plugins"][0]["name"] == "Wetter"
    assert len(list(path.parent.glob("device.json.bak-vor-zeitplan-*"))) == 1
    assert task.signals == 1

    client.post("/api/zeitplan/beta", json={"enabled": False})
    assert json.loads(path.read_text())["zeitplan_beta"] is False
    assert not config.is_schedule_active()


def test_zeitplan_sichern(env):
    client, config, task, path = env
    einschalten(client)
    view = config.get_schedule().views[0]
    (Path(config.plugin_image_dir) / view.get_image_path()).write_bytes(b"png")
    data = ansichten.schedule_for_page(config.get_schedule())
    data["views"][0].update(name="Wetter Berlin", duration_minutes=15,
                            fixed_times=[{"start": "08:00", "end": "10:00", "days": [5]}])
    data["quiet"] = {"enabled": True, "start": "23:00", "end": "06:00"}
    response = client.put("/api/zeitplan", json=data)
    assert response.status_code == 200, response.get_json()
    saved = json.loads(path.read_text())["schedule"]
    assert saved["views"][0]["name"] == "Wetter Berlin"
    assert saved["views"][0]["settings"] == {"stadt": "Berlin"}
    assert saved["quiet"]["enabled"] is True
    assert (Path(config.plugin_image_dir) / "weather_Wetter_Berlin.png").exists()


def test_zeitplan_mit_fehler_wird_nicht_gesichert(env):
    client, config, _, path = env
    einschalten(client)
    data = ansichten.schedule_for_page(config.get_schedule())
    data["views"][0]["duration_minutes"] = 0
    response = client.put("/api/zeitplan", json=data)
    assert response.status_code == 400
    assert "Anzeigedauer" in response.get_json()["error"]
    assert json.loads(path.read_text())["schedule"]["views"][0]["duration_minutes"] == 10


def test_ansicht_anlegen_einstellungen_und_loeschen(env):
    client, config, _, path = env
    einschalten(client)
    response = client.post("/api/ansicht", data={"plugin_id": "clock", "view_name": "Küchenuhr", "format": "24h"})
    assert response.status_code == 200, response.get_json()
    view = config.get_schedule().find_view("clock", "Küchenuhr")
    assert view.settings == {"format": "24h"} and view.rotation
    assert response.get_json()["url"].endswith(f"ansicht={view.id}")

    assert client.post("/api/ansicht", data={"plugin_id": "clock", "view_name": "küchenuhr"}).status_code == 400
    assert client.post("/api/ansicht", data={"plugin_id": "gibtsnicht", "view_name": "X"}).status_code == 400

    view.latest_refresh_time = "2026-10-10T08:00:00"
    response = client.put(f"/api/ansicht/{view.id}/einstellungen", data={"plugin_id": "clock", "format": "12h"})
    assert response.status_code == 200
    assert view.settings == {"format": "12h"} and view.latest_refresh_time is None

    assert client.delete(f"/api/ansicht/{view.id}").status_code == 200
    assert config.get_schedule().get_view(view.id) is None
    assert client.delete(f"/api/ansicht/{view.id}").status_code == 404


def test_jetzt_anzeigen_und_beenden(env):
    client, config, task, path = env
    einschalten(client)
    view = config.get_schedule().views[0]
    response = client.post(f"/api/ansicht/{view.id}/anzeigen", json={"bis": "1h"})
    assert response.status_code == 200
    assert response.get_json()["override"] == {"view_id": view.id, "start": "2026-10-10T08:05:00", "until": "2026-10-10T09:05:00"}
    assert task.shown[-1].view is view

    client.post(f"/api/ansicht/{view.id}/anzeigen", json={"bis": "morgen"})
    assert config.get_schedule().override.until == "2026-10-11T06:00:00"
    client.post(f"/api/ansicht/{view.id}/anzeigen", json={"bis": "immer"})
    assert config.get_schedule().override.until is None
    assert client.post(f"/api/ansicht/{view.id}/anzeigen", json={"bis": "egal"}).status_code == 400

    assert client.delete("/api/zeitplan/manuell").status_code == 200
    assert json.loads(path.read_text())["schedule"]["override"] is None


def test_bild_einer_ansicht(env):
    client, config, _, _ = env
    einschalten(client)
    view = config.get_schedule().views[0]
    assert client.get(f"/api/ansicht/{view.id}/bild").status_code == 404
    (Path(config.plugin_image_dir) / view.get_image_path()).write_bytes(b"\x89PNG")
    assert client.get(f"/api/ansicht/{view.id}/bild").status_code == 200


def test_jetzt_anzeigen_mit_fehler_aendert_nichts(env):
    client, config, task, path = env
    einschalten(client)
    view = config.get_schedule().views[0]
    task.fail = True
    response = client.post(f"/api/ansicht/{view.id}/anzeigen", json={"bis": "1h"})
    assert response.status_code == 500
    assert "Plugin kaputt" in response.get_json()["error"]
    assert config.get_schedule().override is None
    assert json.loads(path.read_text())["schedule"]["override"] is None


def test_tagesplan_endpunkt(env):
    client, config, _, _ = env
    assert client.get("/api/zeitplan/tag").status_code == 409
    einschalten(client)
    plan = client.get("/api/zeitplan/tag").get_json()
    assert plan["date"] == "2026-10-10" and plan["today"]
    assert plan["segments"][0]["view_name"] == "Wetter"
    assert client.get("/api/zeitplan/tag?datum=2026-10-11").get_json()["today"] is False
    assert client.get("/api/zeitplan/tag?datum=morgen").status_code == 400
