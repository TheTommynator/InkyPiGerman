# Hinweise für Claude

- Sprich den Nutzer mit „du“ an und antworte auf Deutsch.
- Die Oberfläche ist komplett auf Deutsch. Neue oder geänderte Texte (Templates, Fehlermeldungen, Plugin-Namen, Display-Ausgaben) ebenfalls auf Deutsch verfassen.
- Arbeite auf einem eigenen Branch und erstelle nach dem Push **immer direkt einen Pull Request nach `main`**, ohne vorher nachzufragen.
- Sobald die Prüfungen auf GitHub grün sind, **merge den Pull Request selbst**, ebenfalls ohne nachzufragen. Sind sie rot, erst den Fehler beheben.
- Vor dem Push prüfen: `python scripts/check.py` und `python -m pytest -q` (wie in `.github/workflows/check.yml`).
- Das Display des Nutzers ist ein **7-Farben-E-Ink-Display** (Schwarz, Weiß, Rot, Grün, Blau, Gelb, Orange). Grautöne, Transparenz und Farbverläufe werden dort zu Punktmustern gerastert – Plugin-Layouts deshalb auf diese reinen Farben abstimmen (siehe Thema „E-Ink (7 Farben)“ im iCloud-Kalender, `EINK_PALETTEN` in `src/plugins/icloud_kalender/kalender_daten.py`).
