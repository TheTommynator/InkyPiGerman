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


def bild(farbe="white", balken=0, start=0):
    """Weißes Bild mit einem schwarzen Balken über `balken` Prozent der Breite ab `start` Prozent."""
    image = Image.new("RGB", (800, 480), farbe)
    if balken:
        ImageDraw.Draw(image).rectangle((8 * start, 0, 8 * (start + balken) - 1, 479), fill="black")
    return image


def p(image):
    return loeschen.pigment_bild(image)


def verlauf_mit(*bilder):
    """Verlauf nach dem ersten Bild (gelöscht) und den weiteren ohne Löschen."""
    verlauf = loeschen.Verlauf()
    for i, image in enumerate(bilder):
        verlauf.merken(p(image), geloescht=(i == 0))
    return verlauf


def test_immer_und_nie():
    assert loeschen.entscheiden("immer", loeschen.Verlauf(), None, None) == (True, None)
    assert loeschen.entscheiden("nie", loeschen.Verlauf(), None, None) == (False, None)


def test_automatisch_nach_neustart_und_einmal_am_tag():
    leer = loeschen.Verlauf()
    assert loeschen.entscheiden("automatisch", leer, p(bild()), 1000, jetzt=2000)[0] is True
    verlauf = verlauf_mit(bild())
    assert loeschen.entscheiden("automatisch", verlauf, p(bild()), 1000, jetzt=1000 + TAG)[0] is True
    assert loeschen.entscheiden("automatisch", verlauf, p(bild()), None, jetzt=1000)[0] is True


def test_veraenderte_flaeche_sammelt_sich_an():
    # Jeder Wechsel ändert nur 10 %, aber jedes Mal an einer anderen Stelle
    verlauf = verlauf_mit(bild(), bild(balken=10, start=0), bild(balken=10, start=10))
    assert round(verlauf.flaeche_nach(p(bild(balken=10, start=20))) * 100) == 30
    clear, reason = loeschen.entscheiden("automatisch", verlauf, p(bild(balken=10, start=20)), 1000, jetzt=2000,
                                         schwelle=30)
    assert clear is True and "30 % der Fläche" in reason
    # Dieselbe Stelle immer wieder: die Fläche wächst nicht
    verlauf = verlauf_mit(bild(), bild(balken=10), bild(), bild(balken=10))
    assert round(verlauf.flaeche_nach(p(bild())) * 100) == 10


def test_hoechstzahl_der_bilder_ohne_loeschen():
    verlauf = verlauf_mit(bild(), bild(balken=5), bild(), bild(balken=5))
    assert verlauf.bilder == 3
    assert loeschen.entscheiden("automatisch", verlauf, p(bild()), 1000, jetzt=2000, max_bilder=4)[0] is False
    clear, reason = loeschen.entscheiden("automatisch", verlauf, p(bild()), 1000, jetzt=2000, max_bilder=3)
    assert clear is True and "3 Bilder" in reason


def test_display_manager_loescht_nur_bei_bedarf(tmp_path):
    config = FakeConfig(tmp_path)
    config.config.update(display_clear_mode="automatisch", display_clear_threshold=30, display_clear_max_updates=2)
    manager = DisplayManager(config)
    calls = []

    def record(image, image_settings=[]):
        calls.append(manager.display.clear_before_display)
        if manager.display.clear_before_display:
            manager.display.report_phase("loeschen")
        manager.display.report_phase("aufbauen")

    manager.display.display_image = record
    for image in (bild(balken=10),      # erstes Bild seit dem Start
                  bild(balken=15),      # kleine Änderung
                  bild(balken=10),      # kleine Änderung
                  bild(balken=15),      # schon 2 Bilder ohne Löschen
                  bild("red")):         # großer Wechsel
        manager.display_image(image, ["skip-enhancement"])
    assert calls == [True, False, False, True, True]
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
