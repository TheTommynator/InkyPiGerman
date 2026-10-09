#!/usr/bin/env python3
"""Schnelle Plausibilitätsprüfung des Codes vor einem Deploy.

Prüft ohne externe Abhängigkeiten:
  - alle Python-Dateien unter src/ lassen sich kompilieren (Syntaxfehler)
  - jedes Plugin hat eine gültige plugin-info.json mit id, class, display_name
  - die id passt zum Ordnernamen, <id>.py existiert und definiert die Klasse

Wird von scripts/deploy.sh auf dem Pi und von der GitHub Action genutzt.
Exit-Code 0 = alles ok, 1 = Fehler gefunden.
"""

import ast
import json
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
PLUGINS_DIR = SRC_DIR / "plugins"
SKIP_PLUGIN_DIRS = {"base_plugin", "__pycache__"}
REQUIRED_KEYS = ("id", "class", "display_name")


def check_syntax(errors):
    for path in sorted(SRC_DIR.rglob("*.py")):
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as e:
            errors.append(f"{path.relative_to(SRC_DIR.parent)}:{e.lineno}: Syntaxfehler: {e.msg}")


def check_plugins(errors):
    for plugin_dir in sorted(p for p in PLUGINS_DIR.iterdir() if p.is_dir()):
        if plugin_dir.name in SKIP_PLUGIN_DIRS:
            continue
        rel = plugin_dir.relative_to(SRC_DIR.parent)
        info_file = plugin_dir / "plugin-info.json"
        if not info_file.is_file():
            # Ohne plugin-info.json wird der Ordner von InkyPi ignoriert
            continue

        try:
            info = json.loads(info_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{rel}/plugin-info.json: ungültiges JSON ({e}) – InkyPi würde nicht starten")
            continue

        if not isinstance(info, dict):
            errors.append(f"{rel}/plugin-info.json: muss ein JSON-Objekt sein")
            continue

        missing = [k for k in REQUIRED_KEYS if not info.get(k)]
        if missing:
            errors.append(f"{rel}/plugin-info.json: fehlende Felder: {', '.join(missing)}")
            continue

        plugin_id = info["id"]
        if plugin_id != plugin_dir.name:
            errors.append(f"{rel}/plugin-info.json: id '{plugin_id}' passt nicht zum Ordnernamen '{plugin_dir.name}'")
            continue

        module_file = plugin_dir / f"{plugin_id}.py"
        if not module_file.is_file():
            errors.append(f"{rel}: {plugin_id}.py fehlt")
            continue

        try:
            tree = ast.parse(module_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue  # schon von check_syntax gemeldet
        classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
        if info["class"] not in classes:
            errors.append(f"{rel}/{plugin_id}.py: Klasse '{info['class']}' nicht gefunden")


def main():
    errors = []
    check_syntax(errors)
    check_plugins(errors)

    if errors:
        print("Prüfung fehlgeschlagen:")
        for error in errors:
            print(f"  ✘ {error}")
        return 1

    print("✔ Prüfung bestanden (Syntax + Plugins)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
