import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils import calibration_wizard as wizard  # noqa: E402


def test_reihenfolge_wie_bildverarbeitung():
    assert wizard.STEP_IDS == ["brightness", "contrast", "saturation", "sharpness"]


@pytest.mark.parametrize("step", wizard.STEP_IDS)
def test_erste_runde_enthaelt_original_und_bleibt_im_bereich(step):
    values = wizard.first_round(step)
    assert 1.0 in values
    assert all(0.0 <= v <= 3.0 for v in values)


def test_saettigung_und_schaerfe_decken_0_bis_3_ab():
    for step in ("saturation", "sharpness"):
        values = wizard.first_round(step)
        assert min(values) == 0.0 and max(values) == 3.0


def test_verfeinern_halbiert_abstand_um_gewaehlten_wert():
    assert wizard.refine([0.0, 0.5, 1.0, 1.5, 2.0, 3.0], 1.5) == [1.0, 1.25, 1.5, 1.75, 2.0]


def test_verfeinern_am_rand_geht_ueber_alte_grenze_hinaus():
    # 2.0 war der höchste Wert der ersten Runde
    assert wizard.refine([0.5, 0.75, 1.0, 1.25, 1.5, 2.0], 2.0) == [1.5, 1.75, 2.0, 2.25, 2.5]


def test_verfeinern_an_der_untergrenze_0():
    assert wizard.refine([0.0, 0.5, 1.0, 1.5, 2.0, 3.0], 0.0) == [0.0, 0.25, 0.5, 0.75, 1.0]


def test_verfeinern_an_der_obergrenze_3():
    assert wizard.refine([0.0, 0.5, 1.0, 1.5, 2.0, 3.0], 3.0) == [1.0, 1.5, 2.0, 2.5, 3.0]


def test_wird_immer_feiner_bis_005():
    values = wizard.first_round("saturation")
    picked = 1.5
    rounds = 0
    while values is not None:
        assert picked in values
        assert all(0.0 <= v <= 3.0 for v in values)
        last = values
        values = wizard.refine(values, picked)
        if values:
            picked = values[1]  # immer etwas nach links wandern
        rounds += 1
        assert rounds < 10
    assert wizard.is_finest(last)
    assert rounds >= 3


def test_ungueltige_auswahl():
    with pytest.raises(ValueError):
        wizard.refine([1.0, 1.5], 1.2)
    with pytest.raises(ValueError):
        wizard.first_round("gibtsnicht")


# ---------- Endpunkte ----------

class FakeRefreshInfo:
    plugin_id = "clock"


class FakeDeviceConfig:
    def __init__(self, tmp_path, image_settings):
        self.config = {"image_settings": image_settings, "resolution": [800, 480]}
        self.current_image_file = str(tmp_path / "current_image.png")
        self.refresh_info = FakeRefreshInfo()

    def get_config(self, key=None, default={}):
        return self.config.get(key, default)

    def update_config(self, config):
        self.config.update(config)

    def get_resolution(self):
        return tuple(self.config["resolution"])

    def get_plugin(self, plugin_id):
        return {"id": plugin_id, "class": "ImageCalibration", "image_settings": ["skip-enhancement"]}

    def get_refresh_info(self):
        return self.refresh_info


class FakeRefreshTask:
    running = False


class FakeDisplayManager:
    def __init__(self):
        self.shown = []

    def display_image(self, image, image_settings=None):
        self.shown.append((image, image_settings))


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    flask = pytest.importorskip("flask")
    pytest.importorskip("PIL")
    pytest.importorskip("jinja2")
    pytest.importorskip("requests")
    from PIL import Image
    from blueprints import calibration
    from plugins.image_calibration.image_calibration import ImageCalibration

    plugin = ImageCalibration({"id": "image_calibration"})
    monkeypatch.setattr(calibration, "get_plugin_instance", lambda config: plugin)
    monkeypatch.setattr(calibration, "_snapshot_path", lambda: str(tmp_path / "snapshot.png"))

    app = flask.Flask(__name__)
    app.register_blueprint(calibration.calibration_bp)
    device_config = FakeDeviceConfig(tmp_path, {"saturation": 1.4})
    Image.new("RGB", (800, 480), (200, 100, 50)).save(device_config.current_image_file)
    display = FakeDisplayManager()
    app.config.update(DEVICE_CONFIG=device_config, REFRESH_TASK=FakeRefreshTask(), DISPLAY_MANAGER=display)
    return app.test_client(), device_config, display, tmp_path


BASE = {"brightness": 1.0, "contrast": 1.0, "saturation": 1.4, "sharpness": 1.0}


def test_start_merkt_aktuelles_bild(app_env):
    client, _, _, tmp_path = app_env
    result = client.post("/bildassistent/start").get_json()
    assert result["has_snapshot"] is True
    assert result["values"]["saturation"] == 1.4
    assert (tmp_path / "snapshot.png").is_file()


def test_runde_zeigt_kacheln_auf_dem_display(app_env):
    client, _, display, _ = app_env
    response = client.post("/bildassistent/runde", json={"step": "contrast", "base": BASE, "motif": "pattern"})
    assert response.status_code == 200
    assert response.get_json()["values"] == wizard.first_round("contrast")
    image, image_settings = display.shown[-1]
    assert image.size == (800, 480)
    assert "skip-enhancement" in image_settings


def test_runde_verfeinert(app_env):
    client, _, _, _ = app_env
    response = client.post("/bildassistent/runde", json={
        "step": "saturation", "base": BASE, "motif": "current",
        "previous": [0.0, 0.5, 1.0, 1.5, 2.0, 3.0], "picked": 1.5,
    })
    assert response.get_json()["values"] == [1.0, 1.25, 1.5, 1.75, 2.0]


def test_runde_ungueltig(app_env):
    client, _, display, _ = app_env
    assert client.post("/bildassistent/runde", json={"step": "x", "base": BASE}).status_code == 400
    assert client.post("/bildassistent/runde", json={"step": "contrast"}).status_code == 400
    assert client.post("/bildassistent/runde", json={
        "step": "contrast", "base": BASE, "previous": [1.0, 1.05], "picked": 1.0}).status_code == 400
    assert display.shown == []


def test_vergleich_und_fertig(app_env):
    client, _, display, _ = app_env
    client.post("/bildassistent/start")
    after = dict(BASE, contrast=1.3)
    assert client.post("/bildassistent/vergleich", json={"before": BASE, "after": after}).status_code == 200
    result = client.post("/bildassistent/fertig").get_json()
    assert result["restored"] is True
    assert len(display.shown) == 2
