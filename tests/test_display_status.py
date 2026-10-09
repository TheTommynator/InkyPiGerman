import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

for module in ("PIL", "numpy"):
    pytest.importorskip(module)

from PIL import Image  # noqa: E402
from display.display_manager import DisplayManager  # noqa: E402


class FakeConfig:
    def __init__(self, tmp_path):
        self.config = {"display_type": "mock", "resolution": [80, 60], "orientation": "horizontal", "output_dir": str(tmp_path / "out")}
        self.current_image_file = str(tmp_path / "current_image.png")

    def get_config(self, key=None, default={}):
        return self.config.get(key, default)

    def get_resolution(self):
        return tuple(self.config["resolution"])

    def update_value(self, key, value, write=False):
        self.config[key] = value


def test_status_vor_und_nach_der_aktualisierung(tmp_path):
    config = FakeConfig(tmp_path)
    manager = DisplayManager(config)

    status = manager.get_status()
    assert status["refreshing"] is False
    assert status["seconds_since_update"] is None
    assert status["expected_seconds"] is None

    manager.display_image(Image.new("RGB", (80, 60), "white"), image_settings=["skip-enhancement"])

    status = manager.get_status()
    assert status["refreshing"] is False
    assert status["seconds_since_update"] is not None
    assert status["expected_seconds"] is not None
    assert config.config["last_display_refresh_seconds"] == status["expected_seconds"]


def test_status_waehrend_der_aktualisierung(tmp_path):
    manager = DisplayManager(FakeConfig(tmp_path))
    started, release = threading.Event(), threading.Event()

    def slow_display(image, image_settings=[]):
        started.set()
        release.wait(5)

    manager.display.display_image = slow_display
    worker = threading.Thread(target=manager.display_image, args=(Image.new("RGB", (80, 60)), ["skip-enhancement"]))
    worker.start()
    assert started.wait(5)
    assert manager.get_status()["refreshing"] is True
    release.set()
    worker.join()
    assert manager.get_status()["refreshing"] is False


def test_fehler_beendet_den_status(tmp_path):
    manager = DisplayManager(FakeConfig(tmp_path))

    def broken(image, image_settings=[]):
        raise RuntimeError("kaputt")

    manager.display.display_image = broken
    with pytest.raises(RuntimeError):
        manager.display_image(Image.new("RGB", (80, 60)), ["skip-enhancement"])
    assert manager.get_status()["refreshing"] is False
