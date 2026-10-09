# Änderungen auf den InkyPi bringen

Der Weg einer Änderung:

```
Änderung (GitHub-Weboberfläche, Claude, lokal)
   │  push auf main
   ▼
GitHub ── Action "Prüfung": Syntax, plugin-info.json, Tests  (rotes ✘ = nicht deployen)
   │
   ▼
Pi: sudo inkypi-deploy  (oder automatisch alle 5 Minuten)
   1. neue Commits holen und anzeigen
   2. neuen Stand prüfen, bevor etwas verändert wird
   3. Code aktualisieren, ggf. pip install / systemd-Dateien
   4. InkyPi neu starten und prüfen, ob die Weboberfläche antwortet
   5. startet InkyPi nicht → automatisch zurück auf den alten Stand
```

Das funktioniert ohne Kopieren, weil das Installationsskript `/usr/local/inkypi/src`
als Symlink auf `src/` im geklonten Repo anlegt. Der Pi läuft also direkt aus dem Clone.

## Einmalige Einrichtung auf dem Pi

1. Prüfen, dass der Clone auf dem Pi auf **dieses** Repo zeigt:

   ```bash
   cd ~/InkyPi            # bzw. wo du das Repo geklont hast
   git remote -v
   ```

   Zeigt `origin` noch auf `fatihak/InkyPi`, umstellen:

   ```bash
   git remote set-url origin https://github.com/TheTommynator/InkyPiGerman.git
   git fetch origin
   git checkout -B main origin/main
   ```

   Lokale Änderungen an versionierten Dateien vorher mit `git status` prüfen und ggf. sichern.
   Eigene Dateien wie `src/config/device.json` und die Bilder sind nicht versioniert
   und bleiben erhalten.

2. Den Deploy-Befehl einrichten (holt dabei gleich den neuesten Stand):

   ```bash
   sudo bash scripts/deploy.sh
   ```

   Ab jetzt gibt es den Befehl `inkypi-deploy`.

3. Optional: automatisches Deploy einschalten, entweder in der Weboberfläche unter
   **Settings → Updates** oder per Befehl:

   ```bash
   sudo inkypi-deploy auto on        # alle 5 Minuten
   sudo inkypi-deploy auto on 15     # alle 15 Minuten (erlaubt: 5, 10, 15, 30, 60)
   ```

## In der Weboberfläche

Unter **Settings → Updates** siehst du:

- einen Schalter für das automatische Update und das Prüfintervall
- welcher Stand installiert ist, wann zuletzt und wann als Nächstes geprüft wird
- ob auf GitHub schon neue Änderungen warten
- die letzten 20 Aktualisierungen mit Ergebnis und den enthaltenen Änderungen
- den Button **Jetzt aktualisieren**

Die Daten dafür schreibt `deploy.sh` nach `/var/lib/inkypi/`.

## Neustart

Nach jedem Update startet das Skript InkyPi automatisch neu, weil Python-Code nur beim
Start geladen wird. Das dauert je nach Pi etwa 10–30 Sekunden. Das Display behält
währenddessen das letzte Bild, die Weboberfläche ist kurz nicht erreichbar.
Ist nichts Neues da, wird auch nichts neu gestartet.

## Befehle

| Befehl | Wirkung |
|---|---|
| `sudo inkypi-deploy` | neuesten Stand holen, prüfen, neu starten |
| `sudo inkypi-deploy status` | Stand auf dem Pi und auf GitHub, Service- und Auto-Status |
| `sudo inkypi-deploy rollback` | zurück auf den Stand vor dem letzten Deploy |
| `sudo inkypi-deploy auto on [MIN]` / `auto off` | automatisches Deploy ein-/ausschalten (MIN: 5, 10, 15, 30, 60) |
| `journalctl -u inkypi-deploy` | Log der automatischen Deploys |
| `journalctl -u inkypi -f` | Live-Log von InkyPi |

## Was bei Fehlern passiert

- **Prüfung schlägt fehl** (z. B. leere `plugin-info.json`, Syntaxfehler): Auf dem Pi
  wird nichts verändert, und InkyPi läuft mit dem alten Stand weiter.
- **InkyPi startet nach dem Update nicht:** Die letzten Log-Zeilen werden angezeigt,
  und der Pi wird automatisch auf den vorherigen Stand zurückgesetzt.
- In beiden Fällen merkt sich das Skript den fehlerhaften Stand. Das Auto-Deploy
  versucht ihn nicht immer wieder, sondern wartet auf den nächsten Commit mit dem Fix.
  `sudo inkypi-deploy` von Hand versucht es trotzdem.
- Nach einem `rollback` bleibt der Pi auf dem alten Stand, bis ein neuer Commit kommt.

## Vor dem Push testen (optional)

```bash
python3 scripts/check.py           # Syntax + Plugins, ohne Abhängigkeiten
python -m pytest                   # Tests
python src/inkypi.py --dev         # Weboberfläche auf http://localhost:8080
```
