"""Logik des Bild-Assistenten: Reihenfolge der Schritte und immer feinere Stufen.

Die Reihenfolge folgt der Bildverarbeitung in apply_image_enhancement():
erst Helligkeit, dann Kontrast, dann Farbe und zum Schluss Schärfe. So baut
jeder Schritt auf den bereits gewählten Werten auf.
"""

VALUE_MIN = 0.0
VALUE_MAX = 3.0
FINEST_STEP = 0.05
REFINE_TILES = 5

STEPS = [
    {
        "id": "brightness",
        "name": "Helligkeit",
        "hint": "Schau auf den Graustufenbalken: Die hellsten Felder sollen sich noch von Weiß "
                "abheben, die dunkelsten noch von Schwarz.",
        "first_round": [0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
    },
    {
        "id": "contrast",
        "name": "Kontrast",
        "hint": "Schwarz soll satt und Weiß sauber wirken, ohne dass Details in hellen oder "
                "dunklen Flächen verschwinden.",
        "first_round": [0.5, 0.75, 1.0, 1.25, 1.5, 2.0],
    },
    {
        "id": "saturation",
        "name": "Sättigung",
        "hint": "Farben sollen kräftig, aber natürlich wirken. Achte besonders auf die Hauttöne "
                "und darauf, dass Flächen nicht fleckig werden.",
        "first_round": [0.0, 0.5, 1.0, 1.5, 2.0, 3.0],
    },
    {
        "id": "sharpness",
        "name": "Schärfe",
        "hint": "Schau auf die feinen Linien und die Schrift: klar und scharf, aber ohne "
                "Treppchen, Säume oder Körnung.",
        "first_round": [0.0, 0.5, 1.0, 1.5, 2.0, 3.0],
    },
]
STEP_IDS = [step["id"] for step in STEPS]


def clamp(value):
    return max(VALUE_MIN, min(float(value), VALUE_MAX))


def first_round(step_id):
    for step in STEPS:
        if step["id"] == step_id:
            return list(step["first_round"])
    raise ValueError(f"Unbekannter Schritt: {step_id}")


def _round_to_step(value):
    return round(round(value / FINEST_STEP) * FINEST_STEP, 2)


def is_finest(values):
    """True, wenn die Stufen schon so fein sind, dass es nicht feiner geht."""
    ordered = sorted(values)
    gaps = [b - a for a, b in zip(ordered, ordered[1:])]
    return not gaps or min(gaps) <= FINEST_STEP + 1e-9


def refine(values, picked):
    """Neue, feinere Stufen rund um den gewählten Wert.

    Der Abstand wird halbiert (bezogen auf den kleineren Abstand zu den
    Nachbarn), damit der gewählte Wert immer in der Mitte liegt. Liegt er am
    Rand, geht die nächste Runde auch über die bisherigen Grenzen hinaus.
    Gibt None zurück, wenn es nicht feiner geht.
    """
    ordered = sorted(set(round(v, 2) for v in values))
    picked = round(float(picked), 2)
    if picked not in ordered:
        raise ValueError("Der gewählte Wert gehört nicht zu dieser Runde.")
    if is_finest(ordered):
        return None

    index = ordered.index(picked)
    gaps = []
    if index > 0:
        gaps.append(picked - ordered[index - 1])
    if index < len(ordered) - 1:
        gaps.append(ordered[index + 1] - picked)
    step = max(FINEST_STEP, _round_to_step(min(gaps) / 2))

    # Kandidaten um den Wert herum, die nächsten innerhalb der Grenzen nehmen
    candidates = []
    for k in range(-REFINE_TILES, REFINE_TILES + 1):
        value = round(picked + k * step, 2)
        if VALUE_MIN - 1e-9 <= value <= VALUE_MAX + 1e-9:
            candidates.append((abs(k), k, value))
    candidates.sort()
    chosen = sorted(value for _, _, value in candidates[:REFINE_TILES])
    return chosen
