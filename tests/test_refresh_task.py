import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

for module in ("PIL", "psutil", "pytz"):
    pytest.importorskip(module)

from PIL import Image  # noqa: E402
import refresh_task as rt  # noqa: E402
from model import RefreshInfo  # noqa: E402


class FakeConfig:
    def __init__(self):
        self.refresh_info = RefreshInfo(None, None, None, None)
        self.writes = 0

    def get_config(self, key=None, default={}):
        return {"timezone": "UTC", "plugin_cycle_interval_seconds": 3600}.get(key, default)

    def get_playlist_manager(self):
        return None

    def get_refresh_info(self):
        return self.refresh_info

    def get_plugin(self, plugin_id):
        return {"id": plugin_id} if plugin_id != "fehlt" else None

    def write_config(self):
        self.writes += 1


class FakePlugin:
    config = {}

    def generate_image(self, settings, device_config):
        return Image.new("RGB", (10, 10), settings.get("farbe", "white"))


class SlowDisplay:
    """Hält den Bildaufbau an, bis der Test ihn freigibt."""

    def __init__(self, fail=False):
        self.started = threading.Event()
        self.release = threading.Event()
        self.shown = []
        self.fail = fail

    def display_image(self, image, image_settings=[]):
        self.started.set()
        self.release.wait(5)
        if self.fail:
            raise RuntimeError("Display kaputt")
        self.shown.append(image.getpixel((0, 0)))


@pytest.fixture
def task(monkeypatch):
    monkeypatch.setattr(rt, "get_plugin_instance", lambda config: FakePlugin())
    created = []

    def make(display):
        t = rt.RefreshTask(FakeConfig(), display)
        t.start()
        created.append((t, display))
        return t

    yield make
    for t, display in created:
        display.release.set()
        t.stop()


def test_manuelles_update_wartet_nicht_auf_das_display(task):
    display = SlowDisplay()
    t = task(display)

    assert t.manual_update(rt.ManualRefresh("bild", {"farbe": "red"})) is True
    # Antwort ist da, obwohl das Display noch aufbaut
    assert display.started.wait(5)
    assert display.shown == []
    display.release.set()


def test_zweites_update_waehrend_des_bildaufbaus(task):
    display = SlowDisplay()
    t = task(display)
    t.manual_update(rt.ManualRefresh("bild", {"farbe": "red"}))
    assert display.started.wait(5)

    result = {}
    worker = threading.Thread(target=lambda: result.update(
        started=t.manual_update(rt.ManualRefresh("bild", {"farbe": "blue"}))))
    worker.start()
    display.release.set()
    worker.join(5)
    assert result["started"] is True

    t.stop()
    assert display.shown == [(255, 0, 0), (0, 0, 255)]


def test_gleiches_bild_wird_nicht_erneut_angezeigt(task):
    display = SlowDisplay()
    display.release.set()
    t = task(display)
    assert t.manual_update(rt.ManualRefresh("bild", {})) is True
    assert t.manual_update(rt.ManualRefresh("bild", {})) is False


def test_fehler_beim_erzeugen_landet_bei_der_anfrage(task):
    t = task(SlowDisplay())
    with pytest.raises(ValueError):
        t.manual_update(rt.ManualRefresh("fehlt", {}))


def test_displayfehler_setzt_den_bildstand_zurueck(task):
    display = SlowDisplay(fail=True)
    display.release.set()
    t = task(display)
    t.manual_update(rt.ManualRefresh("bild", {}))
    t.stop()
    # Beim nächsten Mal wird das Bild erneut gesendet statt übersprungen
    assert t.device_config.refresh_info.image_hash is None
