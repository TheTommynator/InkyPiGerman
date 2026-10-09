#!/bin/bash
#
# InkyPi Deploy – holt den neuesten Stand von GitHub auf den Pi.
#
# Aufruf (auf dem Raspberry Pi):
#   sudo inkypi-deploy               neuesten Stand holen, prüfen, Service neu starten
#   sudo inkypi-deploy rollback      zurück auf den Stand vor dem letzten Deploy
#   sudo inkypi-deploy status        aktuellen Stand, Service- und Auto-Deploy-Status anzeigen
#   sudo inkypi-deploy auto on [MIN] automatisch alle MIN Minuten deployen (Standard: 5)
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

set -uo pipefail

APPNAME="inkypi"
INSTALL_PATH="/usr/local/$APPNAME"
VENV_PATH="$INSTALL_PATH/venv_$APPNAME"
BINPATH="/usr/local/bin"
SERVICE="$APPNAME.service"
DEPLOY_UNIT="$APPNAME-deploy"
HEALTH_URL="${INKYPI_HEALTH_URL:-http://127.0.0.1/}"
HEALTH_TIMEOUT="${INKYPI_HEALTH_TIMEOUT:-90}"

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

require_root() {
  if [ "$EUID" -ne 0 ]; then
    error "Bitte mit sudo ausführen: sudo inkypi-deploy $*"
    exit 1
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
  branch=$(current_branch)

  if [ -n "$(git_repo status --porcelain --untracked-files=no)" ]; then
    error "Es gibt lokale Änderungen an versionierten Dateien in $REPO_DIR:"
    git_repo status --short --untracked-files=no >&2
    error "Bitte erst sichern oder verwerfen (z. B. 'git stash' oder 'git checkout -- <datei>')."
    exit 1
  fi

  info "Hole neuesten Stand von origin/$branch ..."
  if ! git_repo fetch --quiet origin "$branch"; then
    error "git fetch fehlgeschlagen (Netzwerk?)"
    exit 1
  fi

  old=$(git_repo rev-parse HEAD)
  new=$(git_repo rev-parse "origin/$branch")

  if [ "$old" = "$new" ]; then
    info "Bereits aktuell ($(git_repo log -1 --format='%h %s' HEAD))."
    exit 0
  fi

  if $auto && [ -f "$STATE_FAILED" ] && [ "$(cat "$STATE_FAILED")" = "$new" ]; then
    # Dieser Stand ist schon einmal fehlgeschlagen – nicht in Schleife neu versuchen
    exit 0
  fi

  if ! git_repo merge-base --is-ancestor "$old" "$new"; then
    error "Lokaler Stand und origin/$branch sind auseinandergelaufen (lokale Commits auf dem Pi?)."
    error "Bitte manuell klären, z. B.: git -C $REPO_DIR reset --hard origin/$branch"
    exit 1
  fi

  QUIET=false
  echo "Neue Commits:"
  git_repo log --format='  %h %s (%an, %ar)' "$old..$new"

  echo "Prüfe neuen Stand ..."
  if ! check_revision "$new"; then
    error "Deploy abgebrochen – auf dem Pi wurde nichts verändert."
    echo "$new" > "$STATE_FAILED"
    exit 1
  fi

  echo "$old" > "$STATE_PREVIOUS"
  git_repo merge --quiet --ff-only "$new" || { error "git merge fehlgeschlagen"; exit 1; }
  success "Code aktualisiert: $(git_repo log -1 --format='%h %s' HEAD)"

  apply_side_effects "$old" "$new"

  if restart_and_verify; then
    rm -f "$STATE_FAILED"
    success "Deploy abgeschlossen"
    return 0
  fi

  error "Setze automatisch auf den vorherigen Stand $(git_repo log -1 --format='%h' "$old") zurück ..."
  echo "$new" > "$STATE_FAILED"
  git_repo reset --quiet --hard "$old"
  apply_side_effects "$new" "$old"
  restart_and_verify && success "Vorheriger Stand wiederhergestellt"
  exit 1
}

cmd_rollback() {
  local current previous
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
  echo "$(git_repo rev-parse "origin/$(current_branch)")" > "$STATE_FAILED"
  apply_side_effects "$current" "$previous"
  restart_and_verify
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
    echo "Auto:     an ($(systemctl show -p NextElapseUSecRealtime --value "$DEPLOY_UNIT.timer" | sed 's/^$/-/') nächste Prüfung)"
  else
    echo "Auto:     aus"
  fi
  if [ -f "$STATE_FAILED" ]; then
    echo "Hinweis:  Stand $(cut -c1-7 "$STATE_FAILED") ist beim Deploy fehlgeschlagen und wird automatisch übersprungen."
  fi
}

cmd_auto() {
  local mode=${1:-} minutes=${2:-5}
  case "$mode" in
    on)
      cat > "/etc/systemd/system/$DEPLOY_UNIT.service" <<EOF
[Unit]
Description=InkyPi Auto-Deploy von GitHub
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$SCRIPT_PATH auto-run
EOF
      cat > "/etc/systemd/system/$DEPLOY_UNIT.timer" <<EOF
[Unit]
Description=InkyPi Auto-Deploy alle $minutes Minuten

[Timer]
OnBootSec=2min
OnUnitActiveSec=${minutes}min

[Install]
WantedBy=timers.target
EOF
      systemctl daemon-reload
      systemctl enable --now "$DEPLOY_UNIT.timer" >/dev/null 2>&1
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

main() {
  local cmd=${1:-deploy}
  require_root "$@"
  ensure_command_link
  case "$cmd" in
    deploy)   cmd_deploy false ;;
    auto-run) QUIET=true; cmd_deploy true ;;
    rollback) cmd_rollback ;;
    status)   cmd_status ;;
    auto)     shift; cmd_auto "$@" ;;
    -h|--help|help) sed -n '3,12p' "$SCRIPT_PATH" | sed 's/^# \{0,1\}//' ;;
    *) error "Unbekannter Befehl: $cmd (siehe 'inkypi-deploy help')"; exit 1 ;;
  esac
}

main "$@"
