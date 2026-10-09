"""Bildkalibrierung: zeigt dasselbe Motiv mehrfach nebeneinander, jeweils mit
anderen Werten für Sättigung, Kontrast, Schärfe oder Helligkeit.

So lassen sich die Werte direkt auf dem E-Ink-Display vergleichen. Die
globalen Bildeinstellungen werden für dieses Plugin nicht zusätzlich
angewendet (siehe "skip-enhancement" in plugin-info.json), damit jede Kachel
genau die Werte zeigt, die darunter stehen.
"""

import logging
import os
import string

from PIL import Image, ImageDraw, ImageFont, ImageOps

from plugins.base_plugin.base_plugin import BasePlugin
from utils.app_utils import get_font
from utils.image_utils import apply_image_enhancement

logger = logging.getLogger(__name__)

PARAMETERS = {
    "saturation": {"name": "Sättigung", "short": "Sä"},
    "contrast": {"name": "Kontrast", "short": "Ko"},
    "sharpness": {"name": "Schärfe", "short": "Sc"},
    "brightness": {"name": "Helligkeit", "short": "He"},
}
PARAMETER_ORDER = ["saturation", "contrast", "sharpness", "brightness"]

DEFAULT_RANGES = {
    "saturation": (1.0, 2.0),
    "contrast": (0.8, 1.6),
    "sharpness": (1.0, 3.0),
    "brightness": (0.8, 1.2),
}

MAX_TILES = 12
MAX_STEPS = 6
VALUE_LIMITS = (0.0, 5.0)

LABEL_BG = (255, 255, 255)
LABEL_FG = (0, 0, 0)
GRID_BG = (255, 255, 255)

# Farben des 7-Farben-E-Ink-Displays plus Mischtöne, an denen man Sättigung
# und Dithering gut beurteilen kann.
SWATCHES = [
    (0, 0, 0), (255, 255, 255), (255, 0, 0), (255, 255, 0),
    (0, 0, 255), (0, 255, 0), (255, 165, 0),
    (255, 0, 255), (0, 255, 255), (128, 0, 0), (0, 128, 0), (0, 0, 128),
    (230, 190, 160), (190, 140, 100), (140, 90, 60), (128, 128, 128),
]


def parse_float(value, default):
    """Liest eine Zahl, auch mit Komma als Dezimaltrenner."""
    try:
        number = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return default
    if number != number:  # NaN
        return default
    return max(VALUE_LIMITS[0], min(number, VALUE_LIMITS[1]))


def parse_steps(value, default):
    try:
        steps = int(str(value).strip())
    except (TypeError, ValueError):
        steps = default
    return max(1, min(steps, MAX_STEPS))


def value_range(start, end, steps):
    """Gleichmäßig verteilte Werte von start bis end (inklusive)."""
    if steps <= 1:
        return [round(start, 2)]
    step = (end - start) / (steps - 1)
    return [round(start + i * step, 2) for i in range(steps)]


def format_value(value):
    """1.0 -> "1.0", 1.25 -> "1.25" (wie in den Einstellungen mit Punkt)."""
    text = f"{value:.2f}".rstrip("0")
    return text + "0" if text.endswith(".") else text


def read_axis(settings, prefix, fallback_param):
    param = settings.get(f"{prefix}Parameter", fallback_param)
    if param not in PARAMETERS:
        return None
    default_start, default_end = DEFAULT_RANGES[param]
    start = parse_float(settings.get(f"{prefix}From"), default_start)
    end = parse_float(settings.get(f"{prefix}To"), default_end)
    steps = parse_steps(settings.get(f"{prefix}Steps"), 4)
    return param, value_range(start, end, steps)


def build_variants(settings, base_settings):
    """Liefert Spaltenanzahl und die Liste der Varianten (je ein dict mit allen vier Werten)."""
    axis1 = read_axis(settings, "primary", "saturation")
    if axis1 is None:
        raise RuntimeError("Unbekannter Parameter für die Kalibrierung.")
    param1, values1 = axis1

    axis2 = read_axis(settings, "secondary", "none")
    if axis2 is not None and axis2[0] == param1:
        raise RuntimeError("Der zweite Parameter muss sich vom ersten unterscheiden.")

    rows = [(None, None)] if axis2 is None else [(axis2[0], v) for v in axis2[1]]
    if len(values1) * len(rows) > MAX_TILES:
        raise RuntimeError(
            f"Zu viele Varianten ({len(values1) * len(rows)}). Maximal {MAX_TILES} passen sinnvoll aufs Display."
        )

    variants = []
    for param2, value2 in rows:
        for value1 in values1:
            values = dict(base_settings)
            values[param1] = value1
            if param2:
                values[param2] = value2
            variants.append(values)

    columns = len(values1) if axis2 is not None else None
    return param1, (axis2[0] if axis2 else None), columns, variants


def grid_shape(count, width, height, columns=None):
    """Wählt Spalten/Zeilen so, dass die Kacheln möglichst groß werden."""
    if columns:
        return columns, -(-count // columns)
    best = None
    for cols in range(1, count + 1):
        rows = -(-count // cols)
        tile = min(width / cols, height / rows)
        if best is None or tile > best[0]:
            best = (tile, cols, rows)
    return best[1], best[2]


def load_font(size):
    try:
        font = get_font("Jost", size)
        if font:
            return font
    except Exception:
        logger.debug("Schrift Jost nicht verfügbar, nutze Standardschrift")
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def fitting_font(draw, text, max_width, size, min_size=8):
    """Größte Schrift bis `size`, mit der `text` in `max_width` passt."""
    font = load_font(size)
    while size > min_size and draw.textlength(text, font=font) > max_width:
        size -= 1
        font = load_font(size)
    return font


def create_test_pattern(size):
    """Erzeugt ein Testbild mit Farbfeldern, Verläufen und feinen Details."""
    width, height = size
    img = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # Oben: Farbfelder (2 Reihen)
    swatch_h = max(1, int(height * 0.32))
    per_row = len(SWATCHES) // 2
    sw = width / per_row
    for i, color in enumerate(SWATCHES):
        row, col = divmod(i, per_row)
        x0, y0 = int(col * sw), int(row * swatch_h / 2)
        draw.rectangle([x0, y0, int((col + 1) * sw), int((row + 1) * swatch_h / 2)], fill=color)

    # Regenbogen-Verlauf (Farbton) von gesättigt nach blass
    hue_top = swatch_h
    hue_h = max(1, int(height * 0.2))
    hue = Image.linear_gradient("L").rotate(90, expand=True).resize((width, 1))
    hue_strip = Image.merge("HSV", (
        hue.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
        Image.new("L", (width, 1), 255),
        Image.new("L", (width, 1), 255),
    )).convert("RGB")
    fade = Image.linear_gradient("L").resize((width, hue_h))
    hue_block = Image.composite(
        Image.new("RGB", (width, hue_h), (255, 255, 255)),
        hue_strip.resize((width, hue_h)),
        fade.point(lambda v: int(v * 0.7)),
    )
    img.paste(hue_block, (0, hue_top))

    # Graustufen: Verlauf und Stufen (Helligkeit/Kontrast)
    gray_top = hue_top + hue_h
    gray_h = max(1, int(height * 0.18))
    gradient = Image.linear_gradient("L").rotate(90, expand=True).resize((width, gray_h // 2))
    img.paste(gradient.transpose(Image.Transpose.FLIP_LEFT_RIGHT).convert("RGB"), (0, gray_top))
    steps = 11
    for i in range(steps):
        level = int(255 * i / (steps - 1))
        x0 = int(i * width / steps)
        draw.rectangle(
            [x0, gray_top + gray_h // 2, int((i + 1) * width / steps), gray_top + gray_h],
            fill=(level, level, level),
        )

    # Unten: feine Linien, Kreis und Schrift (Schärfe)
    detail_top = gray_top + gray_h
    detail_h = height - detail_top
    if detail_h > 4:
        half = width // 2
        for x in range(0, half, 2):
            draw.line([x, detail_top, x, detail_top + detail_h // 2], fill=(0, 0, 0))
        for y in range(detail_top + detail_h // 2, height, 2):
            draw.line([0, y, half, y], fill=(0, 0, 0))
        radius = max(2, min(detail_h, half) // 2 - 3)
        cx, cy = half + radius + 4, detail_top + detail_h // 2
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=(0, 0, 0), width=2)
        text_x = cx + radius + 6
        font = fitting_font(draw, "Aa Bb 123", width - text_x - 2, max(8, detail_h // 4))
        draw.text((text_x, detail_top + 2), "Aa Bb 123", font=font, fill=(0, 0, 0))
        draw.text((text_x, detail_top + detail_h // 2), "Schärfe", font=font, fill=(200, 0, 0))

    return img


def load_source_image(settings):
    if settings.get("source") != "upload":
        return None
    path = settings.get("calibrationImage")
    if not path:
        raise RuntimeError("Bitte ein Bild hochladen oder das Testbild als Motiv wählen.")
    if not os.path.isfile(path):
        raise RuntimeError("Das hochgeladene Bild wurde nicht gefunden. Bitte erneut hochladen.")
    with Image.open(path) as img:
        return ImageOps.exif_transpose(img).convert("RGB")


def fit_image(image, size):
    return ImageOps.fit(image, size, Image.LANCZOS)


class ImageCalibration(BasePlugin):
    def generate_settings_template(self):
        template_params = super().generate_settings_template()
        template_params["calibration_parameters"] = [
            {"id": p, "name": PARAMETERS[p]["name"], "from": DEFAULT_RANGES[p][0], "to": DEFAULT_RANGES[p][1]}
            for p in PARAMETER_ORDER
        ]
        template_params["max_tiles"] = MAX_TILES
        return template_params

    def generate_image(self, settings, device_config):
        dimensions = device_config.get_resolution()
        if device_config.get_config("orientation") == "vertical":
            dimensions = dimensions[::-1]
        width, height = dimensions

        current = device_config.get_config("image_settings", default={}) or {}
        if settings.get("base") == "neutral":
            base = {p: 1.0 for p in PARAMETER_ORDER}
        else:
            base = {p: parse_float(current.get(p, 1.0), 1.0) for p in PARAMETER_ORDER}

        param1, param2, columns, variants = build_variants(settings, base)

        gap = max(2, width // 200)
        footer_h = max(14, min(width, height) // 22)
        cols, rows = grid_shape(len(variants), width, height - footer_h, columns)
        tile_w = (width - gap * (cols + 1)) // cols
        tile_h = (height - footer_h - gap * (rows + 1)) // rows
        label_h = max(12, min(tile_h // 6, 28))
        image_h = tile_h - label_h
        if tile_w < 20 or image_h < 20:
            raise RuntimeError("Die Kacheln wären zu klein. Bitte weniger Varianten wählen.")

        source = load_source_image(settings)
        sample = fit_image(source, (tile_w, image_h)) if source else create_test_pattern((tile_w, image_h))

        canvas = Image.new("RGB", (width, height), GRID_BG)
        draw = ImageDraw.Draw(canvas)
        varied = [p for p in (param1, param2) if p]
        labels = [
            f"{string.ascii_uppercase[i]}  " + " · ".join(
                f"{PARAMETERS[p]['short']} {format_value(values[p])}" for p in varied)
            for i, values in enumerate(variants)
        ]
        reference_font = load_font(20)
        longest = max(labels, key=lambda text: draw.textlength(text, font=reference_font))
        label_font = fitting_font(draw, longest, tile_w - 6, max(9, int(label_h * 0.7)))

        for index, (values, label) in enumerate(zip(variants, labels)):
            row, col = divmod(index, cols)
            x = gap + col * (tile_w + gap)
            y = gap + row * (tile_h + gap)
            canvas.paste(apply_image_enhancement(sample.copy(), values), (x, y))
            draw.rectangle([x, y + image_h, x + tile_w, y + tile_h], fill=LABEL_BG)
            draw.text((x + 3, y + image_h + (label_h - getattr(label_font, 'size', 10)) // 2 - 1), label,
                      font=label_font, fill=LABEL_FG)

        fixed = [p for p in PARAMETER_ORDER if p not in varied]
        footer = "Fest: " + ", ".join(f"{PARAMETERS[p]['name']} {format_value(base[p])}" for p in fixed)
        footer_font = fitting_font(draw, footer, width - 2 * gap, max(9, int(footer_h * 0.7)))
        draw.text((gap, height - footer_h + (footer_h - getattr(footer_font, 'size', 10)) // 2 - 1), footer,
                  font=footer_font, fill=LABEL_FG)

        return canvas
