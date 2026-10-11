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


def test_schritte_werden_gemeldet_und_fuer_die_schaetzung_gemerkt(tmp_path):
    config = FakeConfig(tmp_path)
    manager = DisplayManager(config)
    seen = []

    def stepwise(image, image_settings=[]):
        for key in ("aufwecken", "loeschen", "farben", "aufbauen", "schlafen"):
            manager.display.report_phase(key)
            seen.append(manager.get_status()["phase"])

    manager.display.display_image = stepwise
    manager.display_image(Image.new("RGB", (80, 60)), ["skip-enhancement"], title="Wetter")

    assert seen == ["Display wird aufgeweckt", "Altes Bild wird gelöscht", "Farben werden umgerechnet",
                    "Neue Farben werden aufgebaut", "Display geht in den Ruhezustand"]
    keys = [key for key, _ in config.config["display_phase_seconds"]]
    assert keys == ["vorbereiten", "aufwecken", "loeschen", "farben", "aufbauen", "schlafen"]
    status = manager.get_status()
    assert status["busy"] is False and status["phase"] is None and status["title"] is None


def test_restzeit_und_schritt_waehrend_der_aktualisierung(tmp_path):
    config = FakeConfig(tmp_path)
    config.config["display_phase_seconds"] = [["vorbereiten", 1], ["loeschen", 20], ["aufbauen", 20]]
    manager = DisplayManager(config)
    started, release = threading.Event(), threading.Event()

    def slow_display(image, image_settings=[]):
        manager.display.report_phase("loeschen")
        started.set()
        release.wait(5)

    manager.display.display_image = slow_display
    worker = threading.Thread(target=manager.display_image,
                              args=(Image.new("RGB", (80, 60)), ["skip-enhancement"], "Kalender"))
    worker.start()
    assert started.wait(5)
    status = manager.get_status()
    release.set()
    worker.join()

    assert status["title"] == "Kalender"
    assert status["phase"] == "Altes Bild wird gelöscht"
    assert (status["step"], status["steps"]) == (2, 3)
    assert 35 < status["remaining_seconds"] <= 40


def test_erzeugen_ohne_bildaufbau(tmp_path):
    manager = DisplayManager(FakeConfig(tmp_path))
    manager.begin_job("Wetter")
    status = manager.get_status()
    assert status["busy"] is True and status["refreshing"] is False
    assert status["phase"] == "Bild wird erzeugt"

    manager.end_job(error="Keine Daten")
    status = manager.get_status()
    assert status["busy"] is False
    assert status["error"] == "Keine Daten"


def test_doppelt_gemeldete_schritte_zaehlen_einmal(tmp_path):
    config = FakeConfig(tmp_path)
    manager = DisplayManager(config)

    def twice(image, image_settings=[]):
        for key in ("loeschen", "aufbauen", "aufbauen", "loeschen"):
            manager.display.report_phase(key)

    manager.display.display_image = twice
    manager.display_image(Image.new("RGB", (80, 60)), ["skip-enhancement"])
    assert [key for key, _ in config.config["display_phase_seconds"]] == ["vorbereiten", "loeschen", "aufbauen"]
