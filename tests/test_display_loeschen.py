import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

for module in ("PIL", "numpy"):
    pytest.importorskip(module)

from PIL import Image, ImageDraw  # noqa: E402
from display import loeschen  # noqa: E402
from display.display_manager import DisplayManager  # noqa: E402
from tests.test_display_status import FakeConfig  # noqa: E402

TAG = 24 * 60 * 60


def bild(farbe="white", balken=0):
    """Weißes Bild mit einem schwarzen Balken über `balken` Prozent der Breite."""
    image = Image.new("RGB", (800, 480), farbe)
    if balken:
        ImageDraw.Draw(image).rectangle((0, 0, 8 * balken - 1, 479), fill="black")
    return image


def test_immer_und_nie():
    assert loeschen.entscheiden("immer", None, None, None) == (True, None)
    assert loeschen.entscheiden("nie", None, None, None) == (False, None)


def test_automatisch_nach_neustart_und_einmal_am_tag():
    a = loeschen.pigment_bild(bild())
    assert loeschen.entscheiden("automatisch", None, a, 1000, jetzt=2000)[0] is True
    assert loeschen.entscheiden("automatisch", a, a, 1000, jetzt=1000 + TAG)[0] is True
    assert loeschen.entscheiden("automatisch", a, a, None, jetzt=1000)[0] is True


def test_automatisch_nach_groesse_der_aenderung():
    vorher = loeschen.pigment_bild(bild(balken=10))
    klein = loeschen.pigment_bild(bild(balken=20))
    gross = loeschen.pigment_bild(bild(balken=60))
    clear, reason = loeschen.entscheiden("automatisch", vorher, klein, 1000, jetzt=2000)
    assert clear is False and "10 %" in reason
    clear, reason = loeschen.entscheiden("automatisch", vorher, gross, 1000, jetzt=2000)
    assert clear is True and "großer Bildwechsel" in reason


def test_display_manager_loescht_nur_bei_bedarf(tmp_path):
    config = FakeConfig(tmp_path)
    config.config["display_clear_mode"] = "automatisch"
    manager = DisplayManager(config)
    calls = []

    def record(image, image_settings=[]):
        calls.append(manager.display.clear_before_display)
        if manager.display.clear_before_display:
            manager.display.report_phase("loeschen")
        manager.display.report_phase("aufbauen")

    manager.display.display_image = record
    manager.display_image(bild(balken=10), ["skip-enhancement"])   # erstes Bild seit dem Start
    manager.display_image(bild(balken=15), ["skip-enhancement"])   # kleine Änderung
    manager.display_image(bild("red"), ["skip-enhancement"])       # großer Wechsel
    assert calls == [True, False, True]
    assert config.config["last_display_clear"] is not None


def test_uebersprungenes_loeschen_bleibt_in_der_schaetzung(tmp_path):
    config = FakeConfig(tmp_path)
    config.config["display_clear_mode"] = "nie"
    config.config["display_phase_seconds"] = [["vorbereiten", 1], ["loeschen", 20], ["aufbauen", 20]]
    manager = DisplayManager(config)
    manager.display.display_image = lambda image, image_settings=[]: manager.display.report_phase("aufbauen")
    manager.display_image(bild(), ["skip-enhancement"])
    plan = config.config["display_phase_seconds"]
    assert [key for key, _ in plan] == ["vorbereiten", "loeschen", "aufbauen"]
    assert dict(plan)["loeschen"] == 20
