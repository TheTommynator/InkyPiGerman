import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

# Die Plugins importieren relativ zu src/ (wie beim Start von InkyPi)
SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))
os.environ.setdefault("SRC_DIR", str(SRC))

from plugins.clock.uhr_worte import (  # noqa: E402
    WORTUHR_RASTER, fuenf_minuten, tageszeit, wortuhr_woerter, zeit_in_worten,
)


@pytest.mark.parametrize("stunde, minute, erwartet", [
    (15, 0, ("", "drei Uhr")),
    (13, 2, ("", "ein Uhr")),
    (15, 7, ("fünf nach", "drei")),
    (15, 15, ("viertel nach", "drei")),
    (15, 24, ("zwanzig nach", "drei")),
    (15, 25, ("fünf vor halb", "vier")),
    (15, 30, ("halb", "vier")),
    (15, 35, ("fünf nach halb", "vier")),
    (15, 45, ("viertel vor", "vier")),
    (23, 55, ("fünf vor", "zwölf")),
    (0, 30, ("halb", "eins")),
    (12, 59, ("fünf vor", "eins")),
])
def test_zeit_in_worten(stunde, minute, erwartet):
    assert zeit_in_worten(stunde, minute) == erwartet


def test_fuenf_minuten_rundet_ab():
    assert [fuenf_minuten(m) for m in (0, 4, 5, 29, 59)] == [0, 0, 5, 25, 55]


def _lesen(stunde, minute):
    woerter = sorted(wortuhr_woerter(stunde, minute))
    return " ".join(WORTUHR_RASTER[z][s:s + n] for z, s, n in woerter)


def test_wortuhr_buchstaben_passen_zu_den_woertern():
    assert _lesen(15, 25) == "ES IST FÜNF VOR HALB VIER"
    assert _lesen(13, 0) == "ES IST EIN UHR"
    assert _lesen(9, 45) == "ES IST VIERTEL VOR ZEHN"
    assert _lesen(11, 20) == "ES IST ZWANZIG NACH ELF"


def test_wortuhr_jede_zeit_lesbar():
    for stunde in range(24):
        for minute in range(0, 60, 5):
            minutenteil, stundenteil = zeit_in_worten(stunde, minute)
            assert _lesen(stunde, minute).replace("ES IST ", "") == f"{minutenteil} {stundenteil}".strip().upper()


def test_tageszeit():
    assert tageszeit(7) == "am Morgen"
    assert tageszeit(15) == "am Nachmittag"
    assert tageszeit(23) == "in der Nacht"


@pytest.mark.parametrize("gesicht", ["Wortuhr", "Uhrzeit in Worten", "Einzeigeruhr", "Stundenring"])
def test_zifferblaetter_nur_reine_farben(gesicht):
    pytest.importorskip("PIL")
    pytest.importorskip("numpy")
    from utils.eink_farben import palette
    from plugins.clock.ruhige_uhren import RUHIGE_UHREN
    farben = {tuple(int(f[i:i + 2], 16) for i in (1, 3, 5)) for f in palette().values()}
    bild = RUHIGE_UHREN[gesicht]((800, 480), datetime(2026, 10, 11, 15, 27), (255, 0, 0), (255, 255, 255))
    assert {f for _, f in bild.getcolors(1 << 20)} <= farben
