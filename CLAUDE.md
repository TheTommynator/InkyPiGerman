# Hinweise für Claude

- Sprich den Nutzer mit „du“ an und antworte auf Deutsch.
- Die Oberfläche ist komplett auf Deutsch. Neue oder geänderte Texte (Templates, Fehlermeldungen, Plugin-Namen, Display-Ausgaben) ebenfalls auf Deutsch verfassen.
- Arbeite auf einem eigenen Branch und erstelle nach dem Push **immer direkt einen Pull Request nach `main`**, ohne vorher nachzufragen.
- Vor dem Push prüfen: `python scripts/check.py` und `python -m pytest -q` (wie in `.github/workflows/check.yml`).
