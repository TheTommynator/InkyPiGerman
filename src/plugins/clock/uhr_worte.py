"""Uhrzeit in deutschen Worten – für Wortuhr, „Uhrzeit in Worten“ und Stundenring.

Ohne Fremdbibliotheken, damit es sich überall testen lässt.
"""

STUNDEN = ["zwölf", "eins", "zwei", "drei", "vier", "fünf", "sechs",
           "sieben", "acht", "neun", "zehn", "elf"]

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]

# ---------------------------------------------------------------------------
# Zeit in Worten
# ---------------------------------------------------------------------------

def fuenf_minuten(minute):
    """Minute auf den Fünf-Minuten-Schritt abgerundet (wie bei einer Wortuhr)."""
    return minute - minute % 5


# Fünf-Minuten-Schritt → (Wörter vor der Stunde, Stunde zählt ab der nächsten)
_SCHRITTE = {
    0: ([], False),
    5: (["fünf", "nach"], False),
    10: (["zehn", "nach"], False),
    15: (["viertel", "nach"], False),
    20: (["zwanzig", "nach"], False),
    25: (["fünf", "vor", "halb"], True),
    30: (["halb"], True),
    35: (["fünf", "nach", "halb"], True),
    40: (["zwanzig", "vor"], True),
    45: (["viertel", "vor"], True),
    50: (["zehn", "vor"], True),
    55: (["fünf", "vor"], True),
}


def zeit_in_worten(stunde, minute):
    """(Minutenteil, Stundenteil), z. B. 15:25 → ("fünf vor halb", "vier")."""
    schritt = fuenf_minuten(minute)
    worte, naechste = _SCHRITTE[schritt]
    h = (stunde + (1 if naechste else 0)) % 12
    if schritt == 0:
        return "", ("ein" if h == 1 else STUNDEN[h]) + " Uhr"
    return " ".join(worte), STUNDEN[h]


def tageszeit(stunde):
    if 5 <= stunde < 10:
        return "am Morgen"
    if 10 <= stunde < 12:
        return "am Vormittag"
    if 12 <= stunde < 14:
        return "am Mittag"
    if 14 <= stunde < 18:
        return "am Nachmittag"
    if 18 <= stunde < 22:
        return "am Abend"
    return "in der Nacht"


def datum_text(zeit):
    return f"{WOCHENTAGE[zeit.weekday()]}, {zeit.day}. {MONATE[zeit.month - 1]}"


# ---------------------------------------------------------------------------
# Wortuhr (deutsches Buchstabenraster)
# ---------------------------------------------------------------------------

WORTUHR_RASTER = [
    "ESKISTAFÜNF",
    "ZEHNZWANZIG",
    "DREIVIERTEL",
    "VORFUNKNACH",
    "HALBAELFÜNF",
    "EINSXAMZWEI",
    "DREIPMJVIER",
    "SECHSNLACHT",
    "SIEBENZWÖLF",
    "ZEHNEUNKUHR",
]

# Wort → (Zeile, erste Spalte, Länge)
_W_MINUTEN = {
    "fünf": (0, 7, 4), "zehn": (1, 0, 4), "zwanzig": (1, 4, 7), "viertel": (2, 4, 7),
    "vor": (3, 0, 3), "nach": (3, 7, 4), "halb": (4, 0, 4),
}
_W_STUNDEN = {
    "ein": (5, 0, 3), "eins": (5, 0, 4), "zwei": (5, 7, 4), "drei": (6, 0, 4), "vier": (6, 7, 4),
    "fünf": (4, 7, 4), "sechs": (7, 0, 5), "sieben": (8, 0, 6), "acht": (7, 7, 4),
    "neun": (9, 3, 4), "zehn": (9, 0, 4), "elf": (4, 5, 3), "zwölf": (8, 6, 5),
}


def wortuhr_woerter(stunde, minute):
    """Leuchtende Wörter als Liste von (Zeile, erste Spalte, Länge)."""
    minutenteil, stundenteil = zeit_in_worten(stunde, minute)
    woerter = [(0, 0, 2), (0, 3, 3)]  # ES IST
    woerter += [_W_MINUTEN[w] for w in minutenteil.split()]
    if stundenteil.endswith(" Uhr"):
        woerter += [_W_STUNDEN[stundenteil[:-4]], (9, 8, 3)]
    else:
        woerter.append(_W_STUNDEN[stundenteil])
    return woerter
