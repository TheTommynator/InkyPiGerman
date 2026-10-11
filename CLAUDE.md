# Hinweise für Claude

- Sprich den Nutzer mit „du“ an und antworte auf Deutsch.
- Die Oberfläche ist komplett auf Deutsch. Neue oder geänderte Texte (Templates, Fehlermeldungen, Plugin-Namen, Display-Ausgaben) ebenfalls auf Deutsch verfassen.
- Arbeite auf einem eigenen Branch und erstelle nach dem Push **immer direkt einen Pull Request nach `main`**, ohne vorher nachzufragen.
- Sobald die Prüfungen auf GitHub grün sind, **merge den Pull Request selbst**, ebenfalls ohne nachzufragen. Sind sie rot, erst den Fehler beheben.
- Vor dem Push prüfen: `python scripts/check.py` und `python -m pytest -q` (wie in `.github/workflows/check.yml`).
- Das Display des Nutzers ist ein **7-Farben-E-Ink-Display von Waveshare** (Schwarz, Weiß, Rot, Grün, Blau, Gelb, Orange; Palette `EINK_PALETTEN["waveshare"]`, also reine RGB-Werte wie `#ff0000`, nicht die gedämpften Inky-Farben). Vorschauen und Simulationen deshalb mit dieser Palette erstellen. Grautöne, Transparenz und Farbverläufe werden dort zu Punktmustern gerastert – Plugin-Layouts deshalb auf diese reinen Farben abstimmen (siehe Thema „E-Ink (7 Farben)“ im iCloud-Kalender, `EINK_PALETTEN` in `src/plugins/icloud_kalender/kalender_daten.py`).
- Farben für Plugins kommen aus `src/utils/eink_farben.py`: `palette(display_type)` liefert die Pigmente, `css_flaeche(name, palette)` reine Farben oder **Mischungen** (zwei Pigmente im festen 2×2-Pixelmuster, z. B. `blau_weiss_50`) als CSS-Hintergrund. Welche Varianten auf dem Display des Nutzers am besten wirken, zeigt das Plugin „Farbtest“ (Tafeln „Grundfarben & Größen“ und „Mischungen“). Blau wirkt auf dem Display in kleinen Elementen (dünne Linien, kleine Schrift, kleine Symbole) fast schwarz und Gelb eher blass – Farbe deshalb vor allem für größere Flächen einsetzen.
