"""Zeitplaner: entscheidet anhand eines Zeitplans, was wann auf dem Display steht.

Regeln, in dieser Reihenfolge:
  1. Manuell („Jetzt anzeigen“) bis zum gewählten Zeitpunkt
  2. Feste Zeit
  3. Ruhezeit – das Display wird nicht aktualisiert
  4. Rotation – die Ansichten wechseln sich in ihrer Reihenfolge ab, jede mit
     ihrer eigenen Anzeigedauer. Die Rotation beginnt jeden Tag um 00:00 mit der
     ersten Ansicht, dadurch liegen die Wechsel fest auf der Uhr (bei 15 Minuten
     z. B. immer um :00, :15, :30, :45) und der Plan ist vorhersehbar.

Der Tagesplan ist eine reine Funktion aus Zeitplan und Datum – es muss kein
Zustand („wo war die Rotation zuletzt“) gespeichert werden.

Alle Zeitpunkte sind naive datetime-Werte in der Ortszeit des Geräts.
Zeitpunkte mit Zeitzone (z. B. latest_refresh_time aus der App) werden auf
ihre Ortszeit reduziert.

Kann eine Ansicht keine neuen Daten holen, bleibt das letzte Bild stehen. Der
Plan läuft normal weiter; innerhalb desselben Abschnitts wird es nach
RETRY_MINUTES noch einmal versucht.
"""

import math
from datetime import date, datetime, timedelta

from zeitplan import MINUTES_PER_DAY, REFRESH_DAILY, REFRESH_INTERVAL, REFRESH_ON_SHOW, parse_hm

KIND_OVERRIDE = "override"
KIND_FIXED = "fixed"
KIND_QUIET = "quiet"
KIND_ROTATION = "rotation"
KIND_IDLE = "idle"

RETRY_MINUTES = 5

# Empfohlene Aktualisierung in Minuten für „Automatisch“ (0 = nur beim Einblenden)
AUTO_REFRESH_MINUTES = {
    "weather": 30,
    "calendar": 15,
    "daily_dashboard": 15,
    "clock": 5,
    "todo_list": 15,
    "rss": 30,
    "github": 60,
    "screenshot": 30,
    "image_url": 60,
    "year_progress": 60,
    "countdown": 60,
    "image_album": 0,
    "image_folder": 0,
    "image_upload": 0,
    "newspaper": 0,
    "comic": 0,
    "apod": 0,
    "wpotd": 0,
    "unsplash": 0,
    "ai_image": 0,
    "ai_text": 0,
}
DEFAULT_AUTO_REFRESH_MINUTES = 60


class Segment:
    """Ein Abschnitt des Tagesplans."""

    def __init__(self, kind, start, end, view=None, fixed_time=None):
        self.kind = kind
        self.start = start
        self.end = end
        self.view = view
        self.fixed_time = fixed_time

    def contains(self, moment):
        return self.start <= moment < self.end

    def __repr__(self):
        name = f" {self.view.name}" if self.view else ""
        return f"Segment({self.kind}{name} {self.start:%H:%M}–{self.end:%H:%M})"


def to_local(value):
    """ISO-Text oder datetime -> naive Ortszeit (None bleibt None)."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=None)


def _at(day, minute):
    return datetime.combine(day, datetime.min.time()) + timedelta(minutes=minute)


# ---------------------------------------------------------------------------
# Bausteine des Tagesplans (Minuten seit Mitternacht des Tages `day`)
# ---------------------------------------------------------------------------

def _override_at(schedule, day, minute):
    """Ende (in Minuten, höchstens 1440) einer manuellen Anzeige zu dieser Minute, sonst None."""
    override = schedule.override
    if not override or not schedule.override_view():
        return None
    moment = _at(day, minute)
    start = to_local(override.start)
    until = to_local(override.until)
    if moment < start or (until and moment >= until):
        return None
    if until is None:
        return MINUTES_PER_DAY
    # aufrunden, damit ein Ende mitten in einer Minute diese Minute noch abdeckt
    return min(MINUTES_PER_DAY, math.ceil((until - _at(day, 0)).total_seconds() / 60))


def _fixed_at(schedule, day, minute):
    """(Ansicht, feste Zeit, Ende in Minuten) einer festen Zeit zu dieser Minute, sonst None."""
    yesterday = day - timedelta(days=1)
    for view in schedule.views:
        for fixed in view.fixed_times:
            start, end = fixed.start_minute(), fixed.end_minute()
            if start == end:
                continue
            if start < end:
                if fixed.starts_on(day) and start <= minute < end:
                    return view, fixed, end
            else:
                if fixed.starts_on(day) and minute >= start:
                    return view, fixed, MINUTES_PER_DAY
                if fixed.starts_on(yesterday) and minute < end:
                    return view, fixed, end
    return None


def _quiet_end(schedule, minute):
    """Ende der Ruhezeit (in Minuten) zu dieser Minute, sonst None."""
    quiet = schedule.quiet
    if not quiet.contains(minute):
        return None
    start, end = parse_hm(quiet.start), parse_hm(quiet.end)
    if start < end:
        return end
    return MINUTES_PER_DAY if minute >= start else end


def _blocked(schedule, day, minute):
    return (_override_at(schedule, day, minute) is not None
            or _fixed_at(schedule, day, minute) is not None
            or _quiet_end(schedule, minute) is not None)


def plan_day(schedule, day):
    """Alle Abschnitte eines Tages (datetime.date) von 00:00 bis 24:00."""
    weekday = day.weekday()
    views = schedule.views
    raw = []  # (kind, start, end, view, fixed)

    def push(kind, start, end, view=None, fixed=None):
        if raw and kind in (KIND_QUIET, KIND_IDLE) and raw[-1][0] == kind and raw[-1][2] == start:
            raw[-1] = (kind, raw[-1][1], end, None, None)
        else:
            raw.append((kind, start, end, view, fixed))

    minute, pointer = 0, -1
    while minute < MINUTES_PER_DAY:
        end = _override_at(schedule, day, minute)
        if end is not None:
            push(KIND_OVERRIDE, minute, end, schedule.override_view())
            minute = end
            continue

        fixed = _fixed_at(schedule, day, minute)
        if fixed:
            view, fixed_time, end = fixed
            for t in range(minute + 1, end):
                if _override_at(schedule, day, t) is not None:
                    end = t
                    break
            push(KIND_FIXED, minute, end, view, fixed_time)
            minute = end
            continue

        end = _quiet_end(schedule, minute)
        if end is not None:
            for t in range(minute + 1, end):
                if _override_at(schedule, day, t) is not None or _fixed_at(schedule, day, t):
                    end = t
                    break
            push(KIND_QUIET, minute, end)
            minute = end
            continue

        pick = None
        for step in range(1, len(views) + 1):
            index = (pointer + step) % len(views)
            if views[index].in_rotation_at(weekday, minute):
                pick = index
                break

        if pick is None:
            end = minute + 1
            while end < MINUTES_PER_DAY and not _blocked(schedule, day, end) \
                    and not any(v.in_rotation_at(weekday, end) for v in views):
                end += 1
            push(KIND_IDLE, minute, end)
            minute = end
            continue

        view = views[pick]
        end = min(MINUTES_PER_DAY, minute + view.duration_minutes)
        for t in range(minute + 1, end):
            if _blocked(schedule, day, t) or not view.in_rotation_at(weekday, t):
                end = t
                break
        push(KIND_ROTATION, minute, end, view)
        pointer = pick
        minute = end

    return [Segment(kind, _at(day, s), _at(day, e), view, fixed) for kind, s, e, view, fixed in raw]


def current_segment(schedule, now):
    """Der Abschnitt, der zum Zeitpunkt `now` gilt."""
    now = to_local(now)
    return next(s for s in plan_day(schedule, now.date()) if s.contains(now))


def upcoming_segments(schedule, now, count=3):
    """Die nächsten `count` Abschnitte nach dem aktuellen (auch über Mitternacht hinweg)."""
    now = to_local(now)
    result = []
    day = now.date()
    for _ in range(8):
        for segment in plan_day(schedule, day):
            if segment.start > now:
                result.append(segment)
                if len(result) == count:
                    return result
        day += timedelta(days=1)
    return result


# ---------------------------------------------------------------------------
# Aktualisierung der Daten
# ---------------------------------------------------------------------------

def refresh_minutes(view):
    """Abstand der Aktualisierung in Minuten; 0 = nur beim Einblenden, None = täglich."""
    mode = view.refresh.mode
    if mode == REFRESH_INTERVAL:
        return max(1, int(view.refresh.minutes or DEFAULT_AUTO_REFRESH_MINUTES))
    if mode == REFRESH_ON_SHOW:
        return 0
    if mode == REFRESH_DAILY:
        return None
    return AUTO_REFRESH_MINUTES.get(view.plugin_id, DEFAULT_AUTO_REFRESH_MINUTES)


def _daily_due(view, now):
    """Letzter fälliger Zeitpunkt der täglichen Aktualisierung bis `now`."""
    hour, minute = map(int, view.refresh.time.split(":"))
    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return due if due <= now else due - timedelta(days=1)


def needs_refresh(view, now, segment):
    """Muss die Ansicht jetzt neue Daten holen, bevor ihr Bild gezeigt wird?"""
    now = to_local(now)
    last = to_local(view.latest_refresh_time)
    if last is None:
        return True
    interval = refresh_minutes(view)
    if interval is None:
        return last < _daily_due(view, now)
    if interval == 0:
        return last < segment.start
    return now - last >= timedelta(minutes=interval)


def next_refresh_at(view, now, segment):
    """Nächste Aktualisierung innerhalb des Abschnitts, sonst None."""
    now = to_local(now)
    last = to_local(view.latest_refresh_time) or now
    interval = refresh_minutes(view)
    if interval == 0:
        return None
    if interval is None:
        upcoming = _daily_due(view, now) + timedelta(days=1)
    else:
        upcoming = max(last + timedelta(minutes=interval), now)
    return upcoming if upcoming < segment.end else None


def retry_at(now, segment):
    """Nach einem Fehler: neuer Versuch nach RETRY_MINUTES, falls der Abschnitt dann noch läuft."""
    attempt = to_local(now) + timedelta(minutes=RETRY_MINUTES)
    return attempt if attempt < segment.end else None


def next_wakeup(schedule, now):
    """Wann der Planer das nächste Mal etwas tun muss: Abschnittswechsel oder Aktualisierung."""
    now = to_local(now)
    segment = current_segment(schedule, now)
    wakeup = segment.end
    if segment.view and segment.kind in (KIND_ROTATION, KIND_FIXED, KIND_OVERRIDE):
        refresh = next_refresh_at(segment.view, now, segment)
        if refresh and refresh < wakeup:
            wakeup = refresh
    return wakeup


# ---------------------------------------------------------------------------
# Überschneidungen fester Zeiten
# ---------------------------------------------------------------------------

def _pieces(fixed):
    """Zerlegt eine feste Zeit in Tagesstücke: (Wochentag, Datum oder None, Start, Ende, Versatz)."""
    start, end = fixed.start_minute(), fixed.end_minute()
    if start == end:
        return []
    parts = [(start, end, 0)] if start < end else [(start, MINUTES_PER_DAY, 0), (0, end, 1)]
    pieces = []
    for a, b, shift in parts:
        if fixed.is_once:
            day = date.fromisoformat(fixed.date) + timedelta(days=shift)
            pieces.append((day.weekday(), day, a, b, shift))
        else:
            for weekday in fixed.days:
                pieces.append(((weekday + shift) % 7, None, a, b, shift))
    return pieces


def fixed_times_overlap(first, second):
    """Überschneiden sich zwei feste Zeiten an irgendeinem Tag?"""
    for wd1, day1, a1, b1, shift1 in _pieces(first):
        for wd2, day2, a2, b2, shift2 in _pieces(second):
            if not (a1 < b2 and a2 < b1):
                continue
            if day1 and day2:
                if day1 == day2:
                    return True
                continue
            if wd1 != wd2:
                continue
            # Einmalige gegen wöchentliche feste Zeit: ausgesetzte Tage zählen nicht
            if day1 and (day1 - timedelta(days=shift2)).isoformat() in second.except_dates:
                continue
            if day2 and (day2 - timedelta(days=shift1)).isoformat() in first.except_dates:
                continue
            return True
    return False


def find_conflict(schedule, fixed):
    """Erste andere feste Zeit, mit der sich `fixed` überschneidet: (Ansicht, feste Zeit) oder None."""
    for view in schedule.views:
        for other in view.fixed_times:
            if other.id != fixed.id and fixed_times_overlap(fixed, other):
                return view, other
    return None


def all_conflicts(schedule):
    """Alle Paare sich überschneidender fester Zeiten (z. B. nach einer Übernahme prüfen)."""
    entries = [(view, fixed) for view in schedule.views for fixed in view.fixed_times]
    conflicts = []
    for i, (view_a, fixed_a) in enumerate(entries):
        for view_b, fixed_b in entries[i + 1:]:
            if fixed_times_overlap(fixed_a, fixed_b):
                conflicts.append(((view_a, fixed_a), (view_b, fixed_b)))
    return conflicts
