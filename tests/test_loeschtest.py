import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

for module in ("PIL", "numpy"):
    pytest.importorskip(module)

from display import loeschen  # noqa: E402
from utils import loeschtest  # noqa: E402


@pytest.mark.parametrize("groesse", [(800, 480), (480, 800)])
def test_szenen_nutzen_nur_pigmente_und_werden_groesser(groesse):
    anteile = []
    pigmente = set(loeschtest_pigmente())
    for szenen_id in loeschtest.SZENEN_IDS:
        vorher, nachher = loeschtest.bilder(szenen_id, groesse)
        assert vorher.size == nachher.size == groesse
        # Text wird kantengeglättet, die Flächen müssen aber reine Pigmente sein
        for bild in (vorher, nachher):
            farben = bild.getcolors(1 << 24)
            anteil_rein = sum(n for n, farbe in farben if farbe in pigmente) / (groesse[0] * groesse[1])
            assert anteil_rein > 0.95
        anteile.append(loeschen.anteil_geaendert(loeschen.pigment_bild(vorher), loeschen.pigment_bild(nachher)))
    assert anteile[0] < 0.15 and anteile[-1] > 0.6
    assert anteile == sorted(anteile)


def loeschtest_pigmente():
    return [loeschtest.SCHWARZ, loeschtest.WEISS, loeschtest.ROT, loeschtest.GRUEN,
            loeschtest.BLAU, loeschtest.GELB, loeschtest.ORANGE]


def e(anteil, bewertung):
    return {"anteil": anteil, "bewertung": bewertung}


def test_empfehlung_schwelle_zwischen_sauber_und_stoerend():
    result = loeschtest.empfehlung([e(4, "sauber"), e(12, "leicht"), e(22, "sauber"), e(45, "stoerend"), e(85, "stoerend")])
    assert result["modus"] == "automatisch"
    assert 22 < result["schwelle"] <= 45


def test_empfehlung_ohne_stoerende_reste():
    result = loeschtest.empfehlung([e(4, "sauber"), e(85, "leicht")])
    assert result == {**result, "modus": "automatisch", "schwelle": 100}


def test_empfehlung_immer_loeschen():
    assert loeschtest.empfehlung([e(4, "stoerend"), e(40, "stoerend")])["modus"] == "immer"


def test_empfehlung_bei_widerspruch_vorsichtig():
    result = loeschtest.empfehlung([e(4, "sauber"), e(20, "stoerend"), e(50, "sauber")])
    assert result["schwelle"] <= 20 and "Hinweis" in result["text"]


def test_ohne_bewertung_keine_empfehlung():
    assert loeschtest.empfehlung([]) is None


def test_schwelle_aus_der_einstellung():
    a = loeschen.pigment_bild(loeschtest.bilder("uhr", (800, 480))[0])
    b = loeschen.pigment_bild(loeschtest.bilder("wetter", (800, 480))[1])
    anteil = loeschen.anteil_geaendert(a, b) * 100
    assert loeschen.entscheiden("automatisch", a, b, 1000, jetzt=2000, schwelle=anteil - 1)[0] is True
    assert loeschen.entscheiden("automatisch", a, b, 1000, jetzt=2000, schwelle=anteil + 1)[0] is False
