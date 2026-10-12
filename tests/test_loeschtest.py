import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

for module in ("PIL", "numpy"):
    pytest.importorskip(module)

from utils import eink_farben, loeschtest  # noqa: E402

PIGMENTE = {eink_farben._rgb(farbe) for farbe in eink_farben.palette("waveshare").values()}


@pytest.mark.parametrize("groesse", [(800, 480), (480, 800)])
def test_ablaeufe_nutzen_nur_pigmente(groesse):
    for ablauf_id in loeschtest.ABLAUF_IDS:
        for schritt in (0, loeschtest.schritte(ablauf_id)):
            bild = loeschtest.bild(ablauf_id, schritt, groesse)
            assert bild.size == groesse
            # Schrift ist kantengeglättet, Flächen und Mischungen bestehen aus reinen Pigmenten
            farben = bild.getcolors(1 << 24)
            rein = sum(n for n, farbe in farben if farbe in PIGMENTE) / (groesse[0] * groesse[1])
            assert rein > 0.95


def test_ablaeufe_bilden_den_alltag_ab():
    g = (800, 480)
    uhr = loeschtest.verlauf_bis("uhr", loeschtest.schritte("uhr"), g)
    assert uhr.bilder >= 10 and loeschtest.flaeche(uhr) < 15      # viele Bilder, wenig Fläche
    tag = [loeschtest.flaeche(loeschtest.verlauf_bis("tag", k, g)) for k in range(1, loeschtest.schritte("tag") + 1)]
    assert tag == sorted(tag) and tag[0] < 20 and tag[-1] > 40   # Fläche wächst über den Tag
    wechsel = loeschtest.verlauf_bis("wechsel", 2, g)
    assert loeschtest.flaeche(wechsel) > 80                        # Ansichtswechsel: fast alles


def e(ablauf, bilder, flaeche, bewertung):
    return {"ablauf": ablauf, "bilder": bilder, "flaeche": flaeche, "bewertung": bewertung}


def test_empfehlung_aus_uhr_und_flaeche():
    ergebnisse = [e("uhr", k, 3 + k * 0.5, "sauber") for k in range(1, 6)] + [e("uhr", 6, 6, "stoerend")]
    ergebnisse += [e("tag", 1, 12, "sauber"), e("tag", 2, 13, "sauber"), e("tag", 3, 25, "leicht"),
                   e("tag", 4, 31, "stoerend")]
    ergebnisse += [e("wechsel", 1, 70, "stoerend")]
    r = loeschtest.empfehlung(ergebnisse)
    assert r["modus"] == "automatisch"
    assert r["max_bilder"] == 5
    assert 25 < r["schwelle"] <= 31


def test_empfehlung_ohne_stoerende_reste():
    r = loeschtest.empfehlung([e("uhr", k, 3, "sauber") for k in range(1, 13)] + [e("wechsel", 7, 100, "leicht")])
    assert (r["modus"], r["max_bilder"], r["schwelle"]) == ("automatisch", 12, 100)
    assert "länger konnte der Test nicht prüfen" in r["text"]


def test_empfehlung_immer_loeschen():
    assert loeschtest.empfehlung([e("uhr", 1, 3, "stoerend")])["modus"] == "immer"


def test_stoerung_durch_viele_bilder_senkt_nicht_die_flaeche():
    # Bei der Uhr stört Bild 8 – das liegt an der Zahl, nicht an der kleinen Fläche
    r = loeschtest.empfehlung([e("uhr", k, 3 + k * 0.5, "sauber") for k in range(1, 8)] + [e("uhr", 8, 7, "stoerend")])
    assert r["max_bilder"] == 7 and r["schwelle"] == 100


def test_ohne_bewertung_keine_empfehlung():
    assert loeschtest.empfehlung([]) is None
