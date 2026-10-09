#!/bin/bash
#
# InkyPi Deploy – holt den neuesten Stand von GitHub auf den Pi.
#
# Aufruf (auf dem Raspberry Pi):
#   sudo inkypi-deploy               neuesten Stand holen, prüfen, Service neu starten
#   sudo inkypi-deploy rollback      zurück auf den Stand vor dem letzten Deploy
#   sudo inkypi-deploy status        aktuellen Stand, Service- und Auto-Deploy-Status anzeigen
#   sudo inkypi-deploy auto on [MIN] automatisch alle MIN Minuten deployen (5, 10, 15, 30, 60; Standard: 5)
#   sudo inkypi-deploy auto off      automatisches Deploy abschalten
#
# Beim ersten Aufruf über "sudo bash scripts/deploy.sh" wird der Befehl
# "inkypi-deploy" nach /usr/local/bin verlinkt.
#
# Ablauf eines Deploys:
#   1. git fetch, neue Commits anzeigen
#   2. neuen Stand mit scripts/check.py prüfen, BEVOR etwas verändert wird
#   3. fast-forward auf den neuen Stand
#   4. bei Bedarf Python-Abhängigkeiten / Service-Dateien aktualisieren
#   5. Service neu starten und prüfen, ob die Weboberfläche antwortet
#   6. startet InkyPi nicht, wird automatisch auf den alten Stand zurückgesetzt
#
# Jede Prüfung und jedes Update wird in /var/lib/inkypi protokolliert und in
# der Weboberfläche unter Settings → Updates angezeigt.

set -uo pipefail

APPNAME="inkypi"
INSTALL_PATH="/usr/local/$APPNAME"
VENV_PATH="$INSTALL_PATH/venv_$APPNAME"
BINPATH="${INKYPI_BINPATH:-/usr/local/bin}"
SERVICE="$APPNAME.service"
DEPLOY_UNIT="$APPNAME-deploy"
STATE_DIR="${INKYPI_STATE_DIR:-/var/lib/$APPNAME}"
LOCK_FILE="/run/$APPNAME-deploy.lock"
HEALTH_URL="${INKYPI_HEALTH_URL:-http://127.0.0.1/}"
HEALTH_TIMEOUT="${INKYPI_HEALTH_TIMEOUT:-90}"
ALLOWED_INTERVALS="5 10 15 30 60"

SOURCE=${BASH_SOURCE[0]}
while [ -h "$SOURCE" ]; do # Symlink (inkypi-deploy) auflösen
  DIR=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )
  SOURCE=$(readlink "$SOURCE")
  [[ $SOURCE != /* ]] && SOURCE=$DIR/$SOURCE
done
SCRIPT_PATH=$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )/$(basename "$SOURCE")
REPO_DIR=$( cd "$(dirname "$SCRIPT_PATH")/.." && pwd )
STATE_PREVIOUS="$REPO_DIR/.git/inkypi-previous-deploy"
STATE_FAILED="$REPO_DIR/.git/inkypi-failed-deploy"

QUIET=false
TRIGGER="${INKYPI_DEPLOY_TRIGGER:-}"

info()    { $QUIET || echo -e "$1"; }
success() { echo -e "$1 [\e[32m\xE2\x9C\x94\e[0m]"; }
error()   { echo -e "$1 [\e[31m\xE2\x9C\x98\e[0m]" >&2; }

# git immer als Besitzer des Repos ausführen (vermeidet "dubious ownership"
# und root-eigene Dateien im Clone)
REPO_OWNER=$(stat -c %U "$REPO_DIR")
git_repo() {
  if [ "$REPO_OWNER" = "root" ]; then
    git -C "$REPO_DIR" "$@"
  else
    sudo -u "$REPO_OWNER" git -C "$REPO_DIR" "$@"
  fi
}

# Schreibt das Ergebnis einer Prüfung nach $STATE_DIR/deploy-last-check.json;
# Deploy-Ereignisse kommen zusätzlich in den Verlauf deploy-history.json.
# Aufruf: record <check|deploy> <ergebnis> <meldung> [alter-commit] [neuer-commit]
PY_RECORD='
import json, os, sys
from datetime import datetime
state_dir, kind, result, message, old, new, trigger = sys.argv[1:8]
commits = []
for line in sys.stdin.read().splitlines():
    parts = line.split("\x1f")
    if len(parts) == 4:
        commits.append(dict(zip(("hash", "subject", "author", "date"), parts)))
entry = {
    "time": datetime.now().astimezone().isoformat(timespec="seconds"),
    "result": result,
    "message": message,
    "trigger": trigger,
    "from": old[:7],
    "to": new[:7],
    "commits": commits,
}
os.makedirs(state_dir, exist_ok=True)

def write(name, data):
    path = os.path.join(state_dir, name)
    with open(path + ".tmp", "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(path + ".tmp", path)

write("deploy-last-check.json", entry)
if kind == "deploy":
    path = os.path.join(state_dir, "deploy-history.json")
    try:
        with open(path) as f:
            history = json.load(f)
    except Exception:
        history = []
    write("deploy-history.json", [entry] + history[:19])
'
record() {
  local kind=$1 result=$2 message=$3 old=${4:-} new=${5:-} commits=""
  if [ -n "$old" ] && [ -n "$new" ] && git_repo merge-base --is-ancestor "$old" "$new" 2>/dev/null; then
    commits=$(git_repo log --format='%h%x1f%s%x1f%an%x1f%cI' "$old..$new" 2>/dev/null)
  fi
  python3 -c "$PY_RECORD" "$STATE_DIR" "$kind" "$result" "$message" "$old" "$new" "$TRIGGER" <<< "$commits" \
    || error "Konnte Status nicht nach $STATE_DIR schreiben"
}

require_root() {
  if [ "$EUID" -ne 0 ]; then
    error "Bitte mit sudo ausführen: sudo inkypi-deploy $*"
    exit 1
  fi
}

# Verhindert, dass Timer und Weboberfläche gleichzeitig deployen
acquire_lock() {
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    info "Es läuft bereits ein Deploy."
    exit 0
  fi
}

ensure_command_link() {
  if [ "$(readlink -f "$BINPATH/$APPNAME-deploy" 2>/dev/null)" != "$SCRIPT_PATH" ]; then
    ln -sf "$SCRIPT_PATH" "$BINPATH/$APPNAME-deploy"
    chmod +x "$SCRIPT_PATH"
    info "Befehl 'inkypi-deploy' eingerichtet ($BINPATH/$APPNAME-deploy)."
  fi
}

current_branch() {
  git_repo rev-parse --abbrev-ref HEAD
}

# Prüft einen Commit in einem temporären Verzeichnis, ohne den Clone anzufassen
check_revision() {
  local rev=$1 tmp rc
  tmp=$(mktemp -d)
  git_repo archive "$rev" scripts src | tar -x -C "$tmp"
  if [ ! -f "$tmp/scripts/check.py" ]; then
    rm -rf "$tmp"
    return 0
  fi
  python3 "$tmp/scripts/check.py"
  rc=$?
  rm -rf "$tmp"
  return $rc
}

# Wartet, bis die Weboberfläche antwortet oder der Service abgestürzt ist
wait_for_service() {
  local waited=0 active sub
  while [ $waited -lt "$HEALTH_TIMEOUT" ]; do
    sleep 3
    waited=$((waited + 3))
    active=$(systemctl show -p ActiveState --value "$SERVICE")
    sub=$(systemctl show -p SubState --value "$SERVICE")
    if [ "$active" = "failed" ] || [ "$sub" = "auto-restart" ]; then
      return 1
    fi
    if [ "$active" = "active" ] && curl -s -o /dev/null --max-time 5 "$HEALTH_URL"; then
      return 0
    fi
  done
  # Kein HTTP-Antwort, aber Service läuft noch – als Erfolg werten, mit Hinweis
  if [ "$(systemctl show -p ActiveState --value "$SERVICE")" = "active" ]; then
    info "Hinweis: Service läuft, aber $HEALTH_URL hat nach ${HEALTH_TIMEOUT}s nicht geantwortet."
    return 0
  fi
  return 1
}

restart_and_verify() {
  local since
  since=$(date '+%Y-%m-%d %H:%M:%S')
  info "Starte $SERVICE neu ..."
  systemctl restart "$SERVICE"
  if wait_for_service; then
    success "InkyPi läuft"
    return 0
  fi
  error "InkyPi ist nach dem Neustart nicht hochgekommen. Log:"
  journalctl -u "$SERVICE" --since "$since" --no-pager -n 40 >&2
  return 1
}

apply_side_effects() {
  local old=$1 new=$2 changed
  changed=$(git_repo diff --name-only "$old" "$new")

  if grep -qx "install/requirements.txt" <<< "$changed"; then
    info "requirements.txt geändert – aktualisiere Python-Abhängigkeiten ..."
    "$VENV_PATH/bin/python" -m pip install -r "$REPO_DIR/install/requirements.txt" -qq \
      && success "Abhängigkeiten aktualisiert" \
      || error "pip install fehlgeschlagen"
  fi

  if grep -qxE "install/inkypi|install/inkypi.service" <<< "$changed"; then
    info "Service-Dateien geändert – aktualisiere systemd ..."
    cp "$REPO_DIR/install/inkypi" "$BINPATH/$APPNAME" && chmod +x "$BINPATH/$APPNAME"
    cp "$REPO_DIR/install/inkypi.service" "/etc/systemd/system/$SERVICE"
    systemctl daemon-reload
  fi
}

cmd_deploy() {
  local auto=${1:-false} branch old new
  acquire_lock
  branch=$(current_branch)

  if [ -n "$(git_repo status --porcelain --untracked-files=no)" ]; then
    error "Es gibt lokale Änderungen an versionierten Dateien in $REPO_DIR:"
    git_repo status --short --untracked-files=no >&2
    error "Bitte erst sichern oder verwerfen (z. B. 'git stash' oder 'git checkout -- <datei>')."
    record check error "Lokale Änderungen auf dem Pi verhindern das Update."
    exit 1
  fi

  info "Hole neuesten Stand von origin/$branch ..."
  if ! git_repo fetch --quiet origin "$branch"; then
    error "git fetch fehlgeschlagen (Netzwerk?)"
    record check error "GitHub nicht erreichbar (Netzwerk?)."
    exit 1
  fi

  old=$(git_repo rev-parse HEAD)
  new=$(git_repo rev-parse "origin/$branch")

  if [ "$old" = "$new" ]; then
    info "Bereits aktuell ($(git_repo log -1 --format='%h %s' HEAD))."
    record check current "Bereits aktuell." "$old" "$new"
    exit 0
  fi

  if $auto && [ -f "$STATE_FAILED" ] && [ "$(cat "$STATE_FAILED")" = "$new" ]; then
    # Dieser Stand ist schon einmal fehlgeschlagen – nicht in Schleife neu versuchen
    record check skipped "Neuer Stand ist fehlgeschlagen und wird übersprungen, bis ein weiterer Commit kommt." "$old" "$new"
    exit 0
  fi

  if ! git_repo merge-base --is-ancestor "$old" "$new"; then
    error "Lokaler Stand und origin/$branch sind auseinandergelaufen (lokale Commits auf dem Pi?)."
    error "Bitte manuell klären, z. B.: git -C $REPO_DIR reset --hard origin/$branch"
    record check error "Stand auf dem Pi und GitHub sind auseinandergelaufen."
    exit 1
  fi

  QUIET=false
  record check running "Update wird installiert ..." "$old" "$new"
  echo "Neue Commits:"
  git_repo log --format='  %h %s (%an, %ar)' "$old..$new"

  echo "Prüfe neuen Stand ..."
  local check_output
  check_output=$(check_revision "$new" 2>&1)
  local check_rc=$?
  echo "$check_output"
  if [ $check_rc -ne 0 ]; then
    error "Deploy abgebrochen – auf dem Pi wurde nichts verändert."
    echo "$new" > "$STATE_FAILED"
    record deploy check_failed "$(grep '✘' <<< "$check_output" | sed 's/^ *✘ //' | head -5)" "$old" "$new"
    exit 1
  fi

  echo "$old" > "$STATE_PREVIOUS"
  if ! git_repo merge --quiet --ff-only "$new"; then
    error "git merge fehlgeschlagen"
    record check error "git merge fehlgeschlagen." "$old" "$new"
    exit 1
  fi
  success "Code aktualisiert: $(git_repo log -1 --format='%h %s' HEAD)"

  apply_side_effects "$old" "$new"

  if restart_and_verify; then
    rm -f "$STATE_FAILED"
    record deploy success "Update installiert, InkyPi läuft." "$old" "$new"
    success "Deploy abgeschlossen"
    return 0
  fi

  error "Setze automatisch auf den vorherigen Stand $(git_repo log -1 --format='%h' "$old") zurück ..."
  echo "$new" > "$STATE_FAILED"
  git_repo reset --quiet --hard "$old"
  apply_side_effects "$new" "$old"
  restart_and_verify && success "Vorheriger Stand wiederhergestellt"
  record deploy rolled_back "InkyPi startete mit dem neuen Stand nicht – alter Stand wiederhergestellt." "$old" "$new"
  exit 1
}

cmd_rollback() {
  local current previous
  acquire_lock
  if [ ! -f "$STATE_PREVIOUS" ]; then
    error "Kein vorheriger Deploy-Stand gespeichert."
    exit 1
  fi
  previous=$(cat "$STATE_PREVIOUS")
  current=$(git_repo rev-parse HEAD)
  if [ "$previous" = "$current" ]; then
    info "Bereits auf dem vorherigen Stand."
    exit 0
  fi
  echo "Rollback: $(git_repo log -1 --format='%h %s' "$current")"
  echo "      ->  $(git_repo log -1 --format='%h %s' "$previous")"
  git_repo reset --quiet --hard "$previous"
  # Damit das Auto-Deploy den zurückgerollten Stand nicht sofort wieder holt
  git_repo rev-parse "origin/$(current_branch)" > "$STATE_FAILED"
  apply_side_effects "$current" "$previous"
  restart_and_verify
  record deploy rollback "Manuell zurückgesetzt auf $(git_repo log -1 --format='%h %s' "$previous")." "$current" "$previous"
}

cmd_status() {
  local branch
  branch=$(current_branch)
  git_repo fetch --quiet origin "$branch" 2>/dev/null
  echo "Repo:     $REPO_DIR ($(git_repo remote get-url origin))"
  echo "Branch:   $branch"
  echo "Auf Pi:   $(git_repo log -1 --format='%h %s (%ar)' HEAD)"
  echo "GitHub:   $(git_repo log -1 --format='%h %s (%ar)' "origin/$branch")"
  local behind
  behind=$(git_repo rev-list --count "HEAD..origin/$branch")
  [ "$behind" -gt 0 ] && echo "          -> $behind neue(r) Commit(s), 'sudo inkypi-deploy' holt sie"
  echo "Service:  $(systemctl is-active "$SERVICE")"
  if systemctl is-enabled --quiet "$DEPLOY_UNIT.timer" 2>/dev/null; then
    echo "Auto:     an, alle $(auto_interval) Minuten"
  else
    echo "Auto:     aus"
  fi
  if [ -f "$STATE_FAILED" ]; then
    echo "Hinweis:  Stand $(cut -c1-7 "$STATE_FAILED") ist beim Deploy fehlgeschlagen und wird automatisch übersprungen."
  fi
}

auto_interval() {
  sed -n 's/^# interval=\([0-9]*\)$/\1/p' "/etc/systemd/system/$DEPLOY_UNIT.timer" 2>/dev/null
}

cmd_auto() {
  local mode=${1:-} minutes=${2:-5} calendar
  case "$mode" in
    on)
      if ! grep -qw -- "$minutes" <<< "$ALLOWED_INTERVALS"; then
        error "Erlaubte Intervalle: $ALLOWED_INTERVALS Minuten"
        exit 1
      fi
      if [ "$minutes" = "60" ]; then calendar="hourly"; else calendar="*:0/$minutes"; fi
      cat > "/etc/systemd/system/$DEPLOY_UNIT.service" <<EOF
[Unit]
Description=InkyPi Auto-Deploy von GitHub
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
Environment=INKYPI_DEPLOY_TRIGGER=auto
ExecStart=$SCRIPT_PATH auto-run
EOF
      cat > "/etc/systemd/system/$DEPLOY_UNIT.timer" <<EOF
# interval=$minutes
[Unit]
Description=InkyPi Auto-Deploy alle $minutes Minuten

[Timer]
OnBootSec=2min
OnCalendar=$calendar

[Install]
WantedBy=timers.target
EOF
      systemctl daemon-reload
      systemctl enable "$DEPLOY_UNIT.timer" >/dev/null 2>&1
      systemctl restart "$DEPLOY_UNIT.timer"
      success "Auto-Deploy aktiv: alle $minutes Minuten (Log: journalctl -u $DEPLOY_UNIT)"
      ;;
    off)
      systemctl disable --now "$DEPLOY_UNIT.timer" >/dev/null 2>&1
      rm -f "/etc/systemd/system/$DEPLOY_UNIT.service" "/etc/systemd/system/$DEPLOY_UNIT.timer"
      systemctl daemon-reload
      success "Auto-Deploy deaktiviert"
      ;;
    *)
      error "Aufruf: sudo inkypi-deploy auto on [MINUTEN] | auto off"
      exit 1
      ;;
  esac
}

# Timer aus älteren Versionen (OnUnitActiveSec) auf das neue Format umstellen,
# damit die Weboberfläche Intervall und nächste Prüfung anzeigen kann
migrate_timer() {
  local timer="/etc/systemd/system/$DEPLOY_UNIT.timer" minutes
  [ -f "$timer" ] && ! grep -q '^# interval=' "$timer" || return 0
  minutes=$(sed -n 's/^OnUnitActiveSec=\([0-9]*\)min$/\1/p' "$timer")
  grep -qw -- "${minutes:-x}" <<< "$ALLOWED_INTERVALS" || minutes=5
  cmd_auto on "$minutes" >/dev/null
}

main() {
  local cmd=${1:-deploy}
  require_root "$@"
  ensure_command_link
  migrate_timer
  case "$cmd" in
    deploy)   TRIGGER=${TRIGGER:-manual}; cmd_deploy false ;;
    auto-run) TRIGGER=${TRIGGER:-auto}; QUIET=true; cmd_deploy true ;;
    rollback) TRIGGER=${TRIGGER:-manual}; cmd_rollback ;;
    status)   cmd_status ;;
    auto)     shift; cmd_auto "$@" ;;
    -h|--help|help) sed -n '3,12p' "$SCRIPT_PATH" | sed 's/^# \{0,1\}//' ;;
    *) error "Unbekannter Befehl: $cmd (siehe 'inkypi-deploy help')"; exit 1 ;;
  esac
}

main "$@"
