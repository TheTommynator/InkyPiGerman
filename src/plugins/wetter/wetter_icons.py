"""Wetter-Icons als SVG – flach, mit kräftiger Kontur, nur reine Farben.

Die Farben kommen aus CSS-Variablen (--i-sonne, --i-regen, --i-blitz), so
schaltet das Stylesheet zwischen „farbig“ und „Linien“ um, ohne dass sich die
Icons ändern. Konturen sind immer in der Textfarbe (currentColor).
"""

import math

KONTUR = 'stroke="currentColor" stroke-width="3.2" stroke-linejoin="round" stroke-linecap="round"'
WEISS = "fill:var(--bg)"


def _sonne(cx=32, cy=32, r=11):
    strahlen = []
    for i in range(8):
        a = i * math.pi / 4
        x1, y1 = cx + math.cos(a) * (r + 5), cy + math.sin(a) * (r + 5)
        x2, y2 = cx + math.cos(a) * (r + 11), cy + math.sin(a) * (r + 11)
        strahlen.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" {KONTUR}/>')
    return "".join(strahlen) + f'<circle cx="{cx}" cy="{cy}" r="{r}" style="fill:var(--i-sonne)" {KONTUR}/>'


def _mond(dx=0, dy=0, s=1.0):
    return (f'<path transform="translate({dx} {dy}) scale({s})" '
            f'd="M38 12 a20 20 0 1 0 16 30 a16 16 0 0 1-16-30z" style="fill:var(--i-sonne)" {KONTUR}/>')


def _wolke(dx=0, dy=0, s=1.0):
    return (f'<path transform="translate({dx} {dy}) scale({s})" '
            'd="M15 52 h33 a11 11 0 0 0 1.5-22 a16 16 0 0 0-30.5-3.5 a12.8 12.8 0 0 0-4 25.5 z" '
            f'style="{WEISS}" {KONTUR}/>')


def _tropfen(x, y):
    return (f'<path d="M{x} {y} q-4 7 0 9 q4-2 0-9z" style="fill:var(--i-regen);stroke:var(--i-regen)" '
            'stroke-width="2.4" stroke-linejoin="round"/>')


def _flocke(x, y):
    linien = (f'<line x1="-4" y1="0" x2="4" y2="0"/><line x1="0" y1="-4" x2="0" y2="4"/>'
              f'<line x1="-3" y1="-3" x2="3" y2="3"/><line x1="-3" y1="3" x2="3" y2="-3"/>')
    return (f'<g transform="translate({x} {y})" style="stroke:var(--i-regen)" stroke-width="2.2" '
            f'stroke-linecap="round">{linien}</g>')


ICONS = {
    "sonne": lambda: _sonne(),
    "mond": lambda: _mond(-6, 2),
    "heiter": lambda: _sonne(23, 22, 9) + _wolke(5, 6),
    "mond_wolke": lambda: _mond(-14, -6, 0.85) + _wolke(5, 6),
    "wolkig": lambda: _wolke(-1, -6),
    "bedeckt": lambda: _wolke(14, -2, 0.8) + _wolke(-4, 2),
    "nebel": lambda: _wolke(-1, -16) + "".join(
        f'<line x1="{12 + i * 3}" y1="{y}" x2="{52 - i * 3}" y2="{y}" {KONTUR}/>' for i, y in enumerate((44, 51, 58))),
    "regen": lambda: _wolke(-1, -12) + _tropfen(22, 46) + _tropfen(32, 50) + _tropfen(42, 46),
    "schauer": lambda: _sonne(22, 18, 8) + _wolke(4, -8) + _tropfen(28, 50) + _tropfen(40, 50),
    "schnee": lambda: _wolke(-1, -12) + _flocke(22, 50) + _flocke(33, 55) + _flocke(44, 50),
    "gewitter": lambda: _wolke(-1, -12) + (
        f'<path d="M34 40 l-8 12 h8 l-4 10 l12-15 h-8 l4-7z" style="fill:var(--i-blitz)" {KONTUR}/>'),
}


def wetter_icon(name, groesse="1em", klasse="icon"):
    zeichnen = ICONS.get(name, ICONS["wolkig"])
    return (f'<svg class="{klasse}" width="{groesse}" height="{groesse}" viewBox="-3 -3 70 70" '
            f'aria-hidden="true">{zeichnen()}</svg>')


# Kleine Symbole für Details und Warnband (24er-Raster)
SYMBOLE = {
    "wind": '<path d="M3 9h11a3 3 0 1 0-3-3M3 15h15a3 3 0 1 1-3 3" fill="none" stroke="currentColor" '
            'stroke-width="2.4" stroke-linecap="round"/>',
    "tropfen": '<path d="M12 2 C8 8 5 11 5 15 a7 7 0 0 0 14 0 c0-4-3-7-7-13z" style="fill:var(--i-regen);'
               'stroke:var(--i-regen)" stroke-width="1.5"/>',
    "uv": '<circle cx="12" cy="12" r="5" style="fill:var(--i-sonne)" stroke="currentColor" stroke-width="2"/>'
          '<path d="M12 1v3M12 20v3M1 12h3M20 12h3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M4.2 19.8l2.1-2.1'
          'M17.7 6.3l2.1-2.1" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "thermometer": '<path d="M10 4a2 2 0 0 1 4 0v10.5a4.5 4.5 0 1 1-4 0z" style="fill:var(--bg)" '
                   'stroke="currentColor" stroke-width="2"/><circle cx="12" cy="18" r="2.2" '
                   'style="fill:var(--i-warm)"/>',
    "feuchte": '<path d="M12 2 C8 8 5 11 5 15 a7 7 0 0 0 14 0 c0-4-3-7-7-13z" style="fill:var(--bg)" '
               'stroke="currentColor" stroke-width="2"/><path d="M9 16a3 3 0 0 0 3 3" fill="none" '
               'stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
    "aufgang": '<path d="M7 18a5 5 0 0 1 10 0z" style="fill:var(--i-sonne)" stroke="currentColor" '
               'stroke-width="2"/><path d="M3 18h18M12 3v6M9 6l3-3 3 3" fill="none" stroke="currentColor" '
               'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "untergang": '<path d="M7 18a5 5 0 0 1 10 0z" style="fill:var(--i-sonne)" stroke="currentColor" '
                 'stroke-width="2"/><path d="M3 18h18M12 3v6M9 6l3 3 3-3" fill="none" stroke="currentColor" '
                 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "warnung": '<path d="M12 2 L23 21 H1 Z" style="fill:var(--warn-innen, var(--bg))" stroke="currentColor" stroke-width="2.2" '
               'stroke-linejoin="round"/><path d="M12 8v6" stroke="currentColor" stroke-width="2.6" '
               'stroke-linecap="round"/><circle cx="12" cy="17.5" r="1.5" fill="currentColor"/>',
}


def symbol(name, klasse="symbol"):
    return f'<svg class="{klasse}" viewBox="0 0 24 24" aria-hidden="true">{SYMBOLE.get(name, "")}</svg>'
