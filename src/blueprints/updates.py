"""Updates: zeigt den Auto-Deploy-Status (scripts/deploy.sh) in der Weboberfläche
und erlaubt, das automatische Update ein-/auszuschalten oder sofort auszulösen."""

from flask import Blueprint, request, jsonify
from datetime import datetime, timedelta
from pathlib import Path
import json
import logging
import os
import re
import shutil
import subprocess

logger = logging.getLogger(__name__)
updates_bp = Blueprint("updates", __name__)

REPO_DIR = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_DIR / "scripts" / "deploy.sh"
STATE_DIR = Path("/var/lib/inkypi")
TIMER_FILE = Path("/etc/systemd/system/inkypi-deploy.timer")
ALLOWED_INTERVALS = [5, 10, 15, 30, 60]


def _available():
    """Updates funktionieren nur auf dem Pi (systemd, root, Git-Clone)."""
    if not shutil.which("systemctl") or not shutil.which("systemd-run"):
        return False, "Nur auf dem Raspberry Pi verfügbar (kein systemd gefunden)."
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        return False, "InkyPi läuft nicht als root – Updates bitte per 'sudo inkypi-deploy' steuern."
    if not DEPLOY_SCRIPT.is_file() or not (REPO_DIR / ".git").exists():
        return False, "Kein Git-Clone mit scripts/deploy.sh gefunden."
    return True, ""


def _git(*args):
    try:
        out = subprocess.run(
            ["git", "-c", f"safe.directory={REPO_DIR}", "-C", str(REPO_DIR), *args],
            capture_output=True, text=True, timeout=10,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def _read_json(name, default):
    try:
        with open(STATE_DIR / name) as f:
            return json.load(f)
    except Exception:
        return default


def _auto_status():
    enabled = subprocess.run(
        ["systemctl", "is-enabled", "--quiet", "inkypi-deploy.timer"]
    ).returncode == 0
    interval = None
    try:
        text = TIMER_FILE.read_text()
        m = re.search(r"^# interval=(\d+)$", text, re.M) or re.search(r"^OnUnitActiveSec=(\d+)min$", text, re.M)
        interval = int(m.group(1)) if m else None
    except Exception:
        pass

    next_run = None
    if enabled and interval:
        now = datetime.now().astimezone()
        minutes = now.hour * 60 + now.minute
        step = minutes // interval * interval + interval
        next_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(minutes=step)
        next_run = next_dt.isoformat(timespec="seconds")
    return {"enabled": enabled, "interval": interval, "next_run": next_run}


def _commits(rev_range):
    out = _git("log", "--format=%h%x1f%s%x1f%an%x1f%cI", rev_range)
    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            commits.append(dict(zip(("hash", "subject", "author", "date"), parts)))
    return commits


@updates_bp.route("/updates/status")
def status():
    available, reason = _available()
    installed = _git("log", "-1", "--format=%h%x1f%s%x1f%cI").split("\x1f")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD") or "main"
    data = {
        "available": available,
        "reason": reason,
        "installed": dict(zip(("hash", "subject", "date"), installed)) if len(installed) == 3 else None,
        # Stand des letzten "git fetch" (macht der Timer bei jeder Prüfung)
        "pending": _commits(f"HEAD..origin/{branch}"),
        "last_check": _read_json("deploy-last-check.json", None),
        "history": _read_json("deploy-history.json", []),
        "auto": _auto_status() if available else {"enabled": False, "interval": None, "next_run": None},
        "intervals": ALLOWED_INTERVALS,
    }
    return jsonify(data)


@updates_bp.route("/updates/auto", methods=["POST"])
def set_auto():
    available, reason = _available()
    if not available:
        return jsonify({"error": reason}), 400

    payload = request.get_json() or {}
    if payload.get("enabled"):
        try:
            interval = int(payload.get("interval", 5))
        except (TypeError, ValueError):
            interval = 5
        if interval not in ALLOWED_INTERVALS:
            return jsonify({"error": f"Erlaubte Intervalle: {ALLOWED_INTERVALS}"}), 400
        cmd = ["bash", str(DEPLOY_SCRIPT), "auto", "on", str(interval)]
    else:
        cmd = ["bash", str(DEPLOY_SCRIPT), "auto", "off"]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        logger.error("Auto-Update umschalten fehlgeschlagen: %s", result.stderr)
        return jsonify({"error": "Auto-Update konnte nicht umgeschaltet werden."}), 500
    return status()


@updates_bp.route("/updates/run", methods=["POST"])
def run_now():
    available, reason = _available()
    if not available:
        return jsonify({"error": reason}), 400

    # Über systemd-run in einer eigenen Unit starten: das Deploy startet InkyPi
    # neu und würde sonst als Kindprozess mit beendet.
    unit = f"inkypi-deploy-web-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    result = subprocess.run(
        ["systemd-run", "--unit", unit, "--collect", "--no-block",
         "--setenv=INKYPI_DEPLOY_TRIGGER=web",
         "bash", str(DEPLOY_SCRIPT), "deploy"],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode != 0:
        logger.error("Update starten fehlgeschlagen: %s", result.stderr)
        return jsonify({"error": "Update konnte nicht gestartet werden."}), 500
    return jsonify({"success": True, "message": "Suche nach Updates gestartet."})
