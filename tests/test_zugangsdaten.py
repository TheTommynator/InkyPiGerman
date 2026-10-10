import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from zugangsdaten import BEKANNTE, KATALOG, katalog_mit_status, pruefe  # noqa: E402


def test_pruefe_name_und_wert():
    assert pruefe("OPEN_AI_SECRET", "sk-123") is None
    assert pruefe("ICLOUD_APP_PASSWORT", "abcd-efgh-ijkl-mnop") is None
    assert pruefe("klein", "x")
    assert pruefe("MIT-STRICH", "x")
    assert pruefe("", "x")
    assert pruefe(None, "x")
    assert pruefe("A", None)
    assert "Zeilenumbrüche" in pruefe("A", "zeile1\nB=gekapert")
    assert pruefe("A", "x" * 5000)


def test_katalog_enthaelt_alle_schluessel_der_plugins():
    plugins = Path(__file__).resolve().parent.parent / "src" / "plugins"
    benutzt = set()
    for datei in plugins.rglob("*.py"):
        text = datei.read_text(encoding="utf-8")
        for teil in text.split('load_env_key("')[1:]:
            benutzt.add(teil.split('"')[0])
    assert benutzt and benutzt <= BEKANNTE, f"Fehlt im Katalog: {benutzt - BEKANNTE}"


def test_katalog_mit_status():
    gruppen = katalog_mit_status({"NASA_SECRET", "EIGENER_KEY"})
    status = {s["key"]: s["gesetzt"] for g in gruppen for s in g["schluessel"]}
    assert status["NASA_SECRET"] is True
    assert status["OPEN_AI_SECRET"] is False
    assert gruppen[-1]["gruppe"] == "Weitere" and status["EIGENER_KEY"] is True
    assert len(katalog_mit_status(set())) == len(KATALOG)
    # Der Katalog selbst bleibt unverändert
    assert all("gesetzt" not in s for g in KATALOG for s in g["schluessel"])


# --- Weboberfläche ---

@pytest.fixture
def client(tmp_path, monkeypatch):
    for modul in ("flask", "dotenv", "PIL", "pytz"):
        pytest.importorskip(modul)
    import flask
    from config import Config
    from blueprints.settings import settings_bp
    from blueprints.zugangsdaten import zugangsdaten_bp

    env = tmp_path / ".env"
    config = Config.__new__(Config)
    monkeypatch.setattr(config, "env_file", lambda: str(env), raising=False)
    for key in BEKANNTE | {"EIGENER_KEY"}:
        monkeypatch.delenv(key, raising=False)

    app = flask.Flask(__name__, template_folder=str(Path(__file__).resolve().parent.parent / "src" / "templates"))
    app.register_blueprint(settings_bp)
    app.register_blueprint(zugangsdaten_bp)
    app.config.update(DEVICE_CONFIG=config)
    return app.test_client(), config, env


def test_speichern_und_loeschen(client):
    c, config, env = client
    assert c.get("/zugangsdaten/status").get_json()["NASA_SECRET"] is False

    antwort = c.post("/zugangsdaten", json={"key": "NASA_SECRET", "wert": "  geheim-123  "})
    assert antwort.status_code == 200 and antwort.get_json()["gesetzt"] is True
    assert 'NASA_SECRET=' in env.read_text() and "geheim-123" in env.read_text()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert os.environ["NASA_SECRET"] == "geheim-123"
    assert c.get("/zugangsdaten/status").get_json()["NASA_SECRET"] is True

    antwort = c.post("/zugangsdaten", json={"key": "NASA_SECRET", "wert": ""})
    assert antwort.get_json()["gesetzt"] is False
    assert "NASA_SECRET" not in env.read_text()
    assert "NASA_SECRET" not in os.environ


def test_andere_eintraege_bleiben_erhalten(client):
    c, _, env = client
    env.write_text("# Kommentar\nOPEN_AI_SECRET=sk-alt\n")
    c.post("/zugangsdaten", json={"key": "NASA_SECRET", "wert": "neu"})
    c.post("/zugangsdaten", json={"key": "OPEN_AI_SECRET", "wert": "sk-neu"})
    text = env.read_text()
    assert "# Kommentar" in text and "sk-neu" in text and "sk-alt" not in text and "NASA_SECRET" in text


def test_werte_werden_nie_angezeigt(client):
    c, _, env = client
    c.post("/zugangsdaten", json={"key": "ICLOUD_APP_PASSWORT", "wert": "abcd-efgh-ijkl-mnop"})
    env.write_text(env.read_text() + "EIGENER_KEY=streng-geheim\n")
    seite = c.get("/zugangsdaten").get_data(as_text=True)
    assert "abcd-efgh" not in seite and "streng-geheim" not in seite
    assert "hinterlegt ✓" in seite and "EIGENER_KEY" in seite
    assert "abcd-efgh" not in c.get("/zugangsdaten/status").get_data(as_text=True)


def test_ungueltige_eingaben(client):
    c, _, env = client
    assert c.post("/zugangsdaten", json={"key": "nasa", "wert": "x"}).status_code == 400
    assert c.post("/zugangsdaten", json={"key": "NASA_SECRET", "wert": "a\nEVIL=1"}).status_code == 400
    assert c.post("/zugangsdaten", data="kein json").status_code == 400
    assert not env.exists()


def test_seite_markiert_gesuchten_schluessel(client):
    c, _, _ = client
    seite = c.get("/zugangsdaten?schluessel=OPEN_WEATHER_MAP_SECRET").get_data(as_text=True)
    assert 'class="zd-eintrag ziel" id="eintrag-OPEN_WEATHER_MAP_SECRET"' in seite


def test_icloud_test(client, monkeypatch):
    for modul in ("requests",):
        pytest.importorskip(modul)
    import requests
    from tests.test_icloud_kalender import ICloudAttrappe

    c, _, _ = client
    assert c.post("/zugangsdaten/icloud/test").status_code == 400

    c.post("/zugangsdaten", json={"key": "ICLOUD_APPLE_ID", "wert": "ich@icloud.com"})
    c.post("/zugangsdaten", json={"key": "ICLOUD_APP_PASSWORT", "wert": "pw"})
    monkeypatch.setattr(requests, "Session", lambda: ICloudAttrappe())
    antwort = c.post("/zugangsdaten/icloud/test")
    assert antwort.status_code == 200
    assert [k["name"] for k in antwort.get_json()["kalender"]] == ["Privat", "Arbeit"]

    monkeypatch.setattr(requests, "Session", lambda: ICloudAttrappe(status=401))
    antwort = c.post("/zugangsdaten/icloud/test")
    assert antwort.status_code == 502 and "app-spezifisches Passwort" in antwort.get_json()["error"]
