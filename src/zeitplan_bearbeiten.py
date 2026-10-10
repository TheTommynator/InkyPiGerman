"""Prüft und übernimmt Änderungen am Zeitplan aus der Weboberfläche.

Die Seite „Ansichten“ schickt beim Sichern alle Ansichten mit ihren
Zeitplan-Feldern (Name, Rotation, Dauer, Aktualisierung, Einschränkung, feste
Zeiten) sowie Ruhezeit und Standard-Anzeigedauer. Plugin-Einstellungen und
der Stand der letzten Aktualisierung bleiben dabei unverändert.

Fehlermeldungen sind für die Oberfläche gedacht und daher auf Deutsch.
"""

import uuid
from datetime import date, datetime, timedelta

from zeitplan import (
    ALL_DAYS, REFRESH_DAILY, REFRESH_INTERVAL, REFRESH_MODES, FixedTime, Limit, QuietTime,
    Refresh, Schedule, View, Window, parse_hm,
)
from zeitplaner import (
    all_conflicts, current_segment, next_refresh_at, plan_day, refresh_minutes, to_local, upcoming_segments,
)

DAY_NAMES = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MAX_MINUTES = 24 * 60


class ScheduleError(ValueError):
    """Ungültige Eingabe; die Meldung kann direkt angezeigt werden."""


def new_id(prefix):
    return prefix + uuid.uuid4().hex[:8]


def check_view_name(name, schedule, ignore_id=None):
    """Prüft einen Ansichtsnamen und gibt ihn bereinigt zurück."""
    name = (name or "").strip()
    if not name:
        raise ScheduleError("Bitte gib der Ansicht einen Namen.")
    if not all(c.isalnum() or c.isspace() or c in "-()" for c in name):
        raise ScheduleError(f"„{name}“: Der Name darf nur Buchstaben, Ziffern, Leerzeichen, Bindestriche und Klammern enthalten.")
    if len(name) > 60:
        raise ScheduleError("Der Name darf höchstens 60 Zeichen lang sein.")
    if any(v.name.lower() == name.lower() and v.id != ignore_id for v in schedule.views):
        raise ScheduleError(f"Es gibt schon eine Ansicht namens „{name}“.")
    return name


def days_summary(days):
    days = sorted(days)
    if days == ALL_DAYS:
        return "täglich"
    if days == [0, 1, 2, 3, 4]:
        return "Mo–Fr"
    if days == [5, 6]:
        return "Sa, So"
    if len(days) > 2 and days == list(range(days[0], days[-1] + 1)):
        return f"{DAY_NAMES[days[0]]}–{DAY_NAMES[days[-1]]}"
    return ", ".join(DAY_NAMES[d] for d in days)


def describe_fixed(fixed):
    """Kurzbeschreibung einer festen Zeit, z. B. „Mo–Fr 06:30–07:30“."""
    if fixed.is_once:
        when = date.fromisoformat(fixed.date).strftime("%d.%m.%Y")
    else:
        when = days_summary(fixed.days)
    end = "24:00" if fixed.end_minute() == MAX_MINUTES else fixed.end
    return f"{when} {fixed.start}–{end}"


def _time(value, what):
    try:
        parse_hm(value)
    except (ValueError, AttributeError):
        raise ScheduleError(f"{what}: ungültige Uhrzeit „{value}“.")
    if value == "24:00":
        return "00:00"
    return value


def _date(value, what):
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        raise ScheduleError(f"{what}: ungültiges Datum „{value}“.")


def _days(values, what):
    try:
        days = sorted({int(d) for d in values or []})
    except (TypeError, ValueError):
        raise ScheduleError(f"{what}: ungültige Wochentage.")
    if not days or any(d < 0 or d > 6 for d in days):
        raise ScheduleError(f"{what}: Bitte wähle mindestens einen Wochentag.")
    return days


def _minutes(value, what, minimum=1):
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        raise ScheduleError(f"{what}: ungültige Dauer.")
    if not minimum <= minutes <= MAX_MINUTES:
        raise ScheduleError(f"{what}: Die Dauer muss zwischen {minimum} Minute(n) und 24 Stunden liegen.")
    return minutes


def _refresh(data, name):
    data = data or {}
    mode = data.get("mode", "auto")
    if mode not in REFRESH_MODES:
        raise ScheduleError(f"„{name}“: unbekannte Art der Aktualisierung.")
    if mode == REFRESH_INTERVAL:
        return Refresh(mode, minutes=_minutes(data.get("minutes"), f"„{name}“, Aktualisierung"))
    if mode == REFRESH_DAILY:
        return Refresh(mode, time=_time(data.get("time"), f"„{name}“, tägliche Aktualisierung"))
    return Refresh(mode)


def _limit(data, name):
    if not data:
        return None
    what = f"„{name}“, Zeitraum"
    windows = []
    for window in data.get("windows") or []:
        start, end = _time(window.get("start"), what), _time(window.get("end"), what)
        if start == end:
            raise ScheduleError(f"{what}: Start und Ende dürfen nicht gleich sein.")
        windows.append(Window(start, end))
    days = _days(data.get("days", ALL_DAYS), what)
    if not windows and days == ALL_DAYS:
        return None
    return Limit(windows=windows, days=days)


def _fixed(data, name):
    what = f"„{name}“, feste Zeit"
    start, end = _time(data.get("start"), what), _time(data.get("end"), what)
    if start == end:
        raise ScheduleError(f"{what}: Start und Ende dürfen nicht gleich sein.")
    fixed_id = str(data.get("id") or new_id("f"))
    if data.get("date"):
        return FixedTime(fixed_id, start, end, date=_date(data["date"], what))
    except_dates = [_date(d, what) for d in data.get("except_dates") or []]
    return FixedTime(fixed_id, start, end, days=_days(data.get("days"), what), except_dates=except_dates)


def apply_update(schedule, payload):
    """Erzeugt aus dem bisherigen Zeitplan und den Änderungen der Oberfläche einen neuen.

    Gibt (neuer Zeitplan, Umbenennungen) zurück; Umbenennungen sind Paare
    (alter Bilddateiname, neuer Bilddateiname). Wirft ScheduleError bei Fehlern.
    """
    entries = payload.get("views")
    if not isinstance(entries, list):
        raise ScheduleError("Ungültige Anfrage.")
    known = {v.id: v for v in schedule.views}
    if sorted(e.get("id") for e in entries) != sorted(known):
        raise ScheduleError("Die Ansichten wurden inzwischen an anderer Stelle geändert. Bitte lade die Seite neu.")

    result = Schedule(
        quiet=schedule.quiet,
        default_duration_minutes=schedule.default_duration_minutes,
        override=schedule.override,
        migrated_from_playlists=schedule.migrated_from_playlists,
    )
    renames = []
    for entry in entries:
        old = known[entry["id"]]
        name = check_view_name(entry.get("name"), result, ignore_id=old.id)
        view = View(
            id=old.id,
            plugin_id=old.plugin_id,
            name=name,
            settings=old.settings,
            rotation=bool(entry.get("rotation")),
            duration_minutes=_minutes(entry.get("duration_minutes"), f"„{name}“, Anzeigedauer"),
            refresh=_refresh(entry.get("refresh"), name),
            limit=_limit(entry.get("limit"), name),
            fixed_times=[_fixed(f, name) for f in entry.get("fixed_times") or []],
            latest_refresh_time=old.latest_refresh_time,
        )
        if view.get_image_path() != old.get_image_path():
            renames.append((old.get_image_path(), view.get_image_path()))
        result.views.append(view)

    quiet = payload.get("quiet")
    if quiet is not None:
        enabled = bool(quiet.get("enabled"))
        start, end = _time(quiet.get("start", "23:00"), "Ruhezeit"), _time(quiet.get("end", "06:00"), "Ruhezeit")
        if enabled and start == end:
            raise ScheduleError("Ruhezeit: Start und Ende dürfen nicht gleich sein.")
        result.quiet = QuietTime(enabled, start, end)

    if payload.get("default_duration_minutes") is not None:
        result.default_duration_minutes = _minutes(payload["default_duration_minutes"], "Standard-Anzeigedauer")

    conflicts = all_conflicts(result)
    if conflicts:
        (view_a, fixed_a), (view_b, fixed_b) = conflicts[0]
        raise ScheduleError(
            f"Feste Zeiten überschneiden sich: „{view_a.name}“ ({describe_fixed(fixed_a)}) "
            f"und „{view_b.name}“ ({describe_fixed(fixed_b)})."
        )
    return result, renames


def schedule_for_page(schedule):
    """Zeitplan als JSON für die Seite – ohne Plugin-Einstellungen."""
    data = schedule.to_dict()
    for view in data["views"]:
        view.pop("settings", None)
    if data["override"] and data["override"].get("view"):
        data["override"]["view"].pop("settings", None)
    return data


def _segment_for_page(segment, day):
    start_of_day = datetime.combine(day, datetime.min.time())
    view = segment.view
    return {
        "kind": segment.kind,
        "start": int((segment.start - start_of_day).total_seconds() // 60),
        "end": int((segment.end - start_of_day).total_seconds() // 60),
        "view_id": view.id if view else None,
        "view_name": view.name if view else None,
        "plugin_id": view.plugin_id if view else None,
        "fixed_id": segment.fixed_time.id if segment.fixed_time else None,
        "refresh_minutes": refresh_minutes(view) if view else None,
    }


def _same_segment(a, b):
    return (a.kind == b.kind and (a.view.id if a.view else None) == (b.view.id if b.view else None)
            and (a.fixed_time.id if a.fixed_time else None) == (b.fixed_time.id if b.fixed_time else None))


def day_plan_for_page(schedule, day, now, manual=None):
    """Tagesplan für die Startseite: Abschnitte in Minuten seit Mitternacht.

    Für den heutigen Tag kommen „Jetzt“ (mit Datenstand) und „Als Nächstes“ dazu.
    `now` ist die aktuelle Ortszeit als naive datetime.
    `manual` = (Zeitpunkt, Name), wenn zuletzt etwas außerhalb des Zeitplans angezeigt
    wurde (z. B. „Jetzt anzeigen“ auf der Plugin-Seite). Liegt das im aktuellen
    Abschnitt, steht es bis zur nächsten Planänderung auf dem Display.
    """
    now = to_local(now)
    result = {
        "date": day.isoformat(),
        "today": day == now.date(),
        "segments": [_segment_for_page(s, day) for s in plan_day(schedule, day)],
    }
    if not result["today"]:
        return result

    result["now_minute"] = now.hour * 60 + now.minute
    current = current_segment(schedule, now)
    # Abschnitte, die über Mitternacht weiterlaufen, zählen als einer
    following = upcoming_segments(schedule, now, 4)
    end = current.end
    while following and following[0].start == end and _same_segment(following[0], current):
        end = following.pop(0).end
    info = {"kind": current.kind, "end": end.strftime("%H:%M"),
            "minutes_left": max(0, int((end - now).total_seconds() // 60))}
    if current.kind == "override" and schedule.override and schedule.override.until is None:
        info["open_end"] = True  # „Jetzt anzeigen … bis ich es beende“
    if current.view:
        view = current.view
        last = to_local(view.latest_refresh_time)
        upcoming = next_refresh_at(view, now, current)
        info.update({
            "view_id": view.id,
            "view_name": view.name,
            "plugin_id": view.plugin_id,
            "data_from": last.strftime("%H:%M") if last and last.date() == now.date() else None,
            "next_refresh": upcoming.strftime("%H:%M") if upcoming else None,
        })
    if manual:
        shown_at = to_local(manual[0])
        # `now` ist auf die Minute gerundet, daher eine Minute Spielraum
        if shown_at and current.start <= shown_at < now + timedelta(minutes=1):
            info["manual"] = {
                "name": manual[1],
                "since": shown_at.strftime("%H:%M"),
                # so lange hält der Refresh-Task das Bild fest (siehe RefreshTask._remember_manual)
                "until": current.end.strftime("%H:%M"),
            }
    result["now"] = info

    if following:
        nxt = following[0]
        result["next"] = {
            "kind": nxt.kind,
            "start": nxt.start.strftime("%H:%M"),
            "tomorrow": nxt.start.date() == now.date() + timedelta(days=1),
            "view_name": nxt.view.name if nxt.view else None,
        }
    return result
