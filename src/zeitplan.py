"""Zeitplan: Ansichten, feste Zeiten und Ruhezeit – der Nachfolger der Playlists.

Begriffe:
  - Ansicht (View): ein eingerichtetes Plugin, z. B. „Wetter Berlin“. Sie kann in
    der Rotation laufen (mit eigener Anzeigedauer und optionaler Einschränkung
    auf Zeiträume/Wochentage) und/oder feste Zeiten haben.
  - Feste Zeit (FixedTime): wöchentlich an bestimmten Tagen oder einmalig an
    einem Datum; währenddessen bleibt die Ansicht auf dem Display.
  - Ruhezeit (QuietTime): in diesem Zeitraum wird das Display nicht aktualisiert.
  - Manuell (Override): „Jetzt anzeigen“ bis zu einem Zeitpunkt oder unbegrenzt.

Wochentage werden wie bei date.weekday() gezählt: 0 = Montag … 6 = Sonntag.
Uhrzeiten werden als "HH:MM" gespeichert; "24:00" bzw. "00:00" als Ende
bedeutet Mitternacht.

Dieses Modul hat bewusst keine Abhängigkeiten zum Rest von InkyPi, damit es
sich einfach testen lässt. Die Übernahme der alten Playlists liest
playlist_config nur und verändert sie nicht.
"""

SCHEDULE_VERSION = 1
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]
MINUTES_PER_DAY = 1440

REFRESH_AUTO = "auto"
REFRESH_ON_SHOW = "on_show"
REFRESH_INTERVAL = "interval"
REFRESH_DAILY = "daily"
REFRESH_MODES = (REFRESH_AUTO, REFRESH_ON_SHOW, REFRESH_INTERVAL, REFRESH_DAILY)


def parse_hm(value):
    """Wandelt "HH:MM" in Minuten seit Mitternacht um ("24:00" -> 1440)."""
    hours, minutes = value.split(":")
    total = int(hours) * 60 + int(minutes)
    if not 0 <= total <= MINUTES_PER_DAY:
        raise ValueError(f"Ungültige Uhrzeit: {value}")
    return total


def format_hm(minutes):
    """Wandelt Minuten in "HH:MM" um; 1440 wird zu "00:00"."""
    minutes %= MINUTES_PER_DAY
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _clean_days(days):
    return sorted({int(d) for d in days if 0 <= int(d) <= 6})


class Window:
    """Ein Zeitraum innerhalb eines Tages, darf über Mitternacht gehen (21:00–03:00)."""

    def __init__(self, start, end):
        self.start = start
        self.end = end

    def contains(self, minute):
        start, end = parse_hm(self.start), parse_hm(self.end)
        if end == 0:
            end = MINUTES_PER_DAY
        if start == end:
            return False
        if start < end:
            return start <= minute < end
        return minute >= start or minute < end

    def to_dict(self):
        return {"start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, data):
        return cls(data["start"], data["end"])

    def __eq__(self, other):
        return isinstance(other, Window) and (self.start, self.end) == (other.start, other.end)

    def __repr__(self):
        return f"Window({self.start}–{self.end})"


class Limit:
    """Schränkt ein, wann eine Ansicht in der Rotation läuft.

    Die Ansicht läuft an den angegebenen Wochentagen innerhalb eines der Zeiträume.
    """

    def __init__(self, windows=None, days=None):
        self.windows = list(windows or [])
        self.days = _clean_days(ALL_DAYS if days is None else days)

    def allows(self, weekday, minute):
        if weekday not in self.days:
            return False
        if not self.windows:
            return True
        return any(w.contains(minute) for w in self.windows)

    def to_dict(self):
        return {"windows": [w.to_dict() for w in self.windows], "days": self.days}

    @classmethod
    def from_dict(cls, data):
        return cls(
            windows=[Window.from_dict(w) for w in data.get("windows", [])],
            days=data.get("days"),
        )


class FixedTime:
    """Eine feste Zeit: wöchentlich an `days` oder einmalig an `date` (YYYY-MM-DD).

    `except_dates` enthält Tage, an denen eine wöchentliche feste Zeit ausgesetzt ist.
    Liegt `end` vor `start`, endet die feste Zeit am nächsten Tag.
    """

    def __init__(self, id, start, end, days=None, date=None, except_dates=None):
        self.id = id
        self.start = start
        self.end = end
        self.date = date
        self.days = [] if date else _clean_days(days or [])
        self.except_dates = sorted(set(except_dates or []))

    @property
    def is_once(self):
        return bool(self.date)

    def start_minute(self):
        return parse_hm(self.start)

    def end_minute(self):
        """Ende in Minuten; Mitternacht als Ende zählt als 1440."""
        end = parse_hm(self.end)
        return MINUTES_PER_DAY if end == 0 and self.start_minute() > 0 else end

    def wraps_midnight(self):
        return self.end_minute() < self.start_minute()

    def starts_on(self, day):
        """Beginnt an `day` (datetime.date) eine Wiederholung dieser festen Zeit?"""
        if self.is_once:
            return self.date == day.isoformat()
        return day.weekday() in self.days and day.isoformat() not in self.except_dates

    def to_dict(self):
        data = {"id": self.id, "start": self.start, "end": self.end}
        if self.is_once:
            data["date"] = self.date
        else:
            data["days"] = self.days
            data["except_dates"] = self.except_dates
        return data

    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data["id"],
            start=data["start"],
            end=data["end"],
            days=data.get("days"),
            date=data.get("date"),
            except_dates=data.get("except_dates"),
        )


class Refresh:
    """Wie oft eine Ansicht neue Daten holt, solange sie angezeigt wird.

    auto      – Vorgabe des Plugins
    on_show   – nur beim Einblenden
    interval  – alle `minutes` Minuten
    daily     – einmal täglich ab `time` ("HH:MM", übernommen aus den Playlists)
    """

    def __init__(self, mode=REFRESH_AUTO, minutes=None, time=None):
        if mode not in REFRESH_MODES:
            mode = REFRESH_AUTO
        self.mode = mode
        self.minutes = minutes
        self.time = time

    def to_dict(self):
        data = {"mode": self.mode}
        if self.mode == REFRESH_INTERVAL:
            data["minutes"] = self.minutes
        if self.mode == REFRESH_DAILY:
            data["time"] = self.time
        return data

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        return cls(data.get("mode", REFRESH_AUTO), data.get("minutes"), data.get("time"))

    @classmethod
    def from_playlist_refresh(cls, refresh):
        """Übernimmt die Aktualisierungs-Einstellung einer Plugin-Instanz aus den Playlists."""
        refresh = refresh or {}
        if refresh.get("interval"):
            return cls(REFRESH_INTERVAL, minutes=max(1, round(int(refresh["interval"]) / 60)))
        if refresh.get("scheduled"):
            return cls(REFRESH_DAILY, time=refresh["scheduled"])
        return cls(REFRESH_AUTO)


class View:
    """Eine Ansicht: ein eingerichtetes Plugin mit Rotation und festen Zeiten."""

    def __init__(self, id, plugin_id, name, settings=None, rotation=True, duration_minutes=10,
                 refresh=None, limit=None, fixed_times=None, latest_refresh_time=None):
        self.id = id
        self.plugin_id = plugin_id
        self.name = name
        self.settings = settings or {}
        self.rotation = rotation
        self.duration_minutes = max(1, int(duration_minutes))
        self.refresh = refresh or Refresh()
        self.limit = limit
        self.fixed_times = list(fixed_times or [])
        self.latest_refresh_time = latest_refresh_time

    def in_rotation_at(self, weekday, minute):
        """Darf die Ansicht zu diesem Zeitpunkt in der Rotation laufen?"""
        if not self.rotation:
            return False
        return self.limit is None or self.limit.allows(weekday, minute)

    def get_image_path(self):
        """Gleicher Dateiname wie bei Plugin-Instanzen, damit vorhandene Bilder weiter passen."""
        return f"{self.plugin_id}_{self.name.replace(' ', '_')}.png"

    def to_dict(self):
        return {
            "id": self.id,
            "plugin_id": self.plugin_id,
            "name": self.name,
            "settings": self.settings,
            "rotation": self.rotation,
            "duration_minutes": self.duration_minutes,
            "refresh": self.refresh.to_dict(),
            "limit": self.limit.to_dict() if self.limit else None,
            "fixed_times": [f.to_dict() for f in self.fixed_times],
            "latest_refresh_time": self.latest_refresh_time,
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            id=data["id"],
            plugin_id=data["plugin_id"],
            name=data["name"],
            settings=data.get("settings"),
            rotation=data.get("rotation", True),
            duration_minutes=data.get("duration_minutes", 10),
            refresh=Refresh.from_dict(data.get("refresh")),
            limit=Limit.from_dict(data["limit"]) if data.get("limit") else None,
            fixed_times=[FixedTime.from_dict(f) for f in data.get("fixed_times", [])],
            latest_refresh_time=data.get("latest_refresh_time"),
        )


class QuietTime:
    """Ruhezeit: das Display wird nicht aktualisiert (feste Zeiten haben Vorrang)."""

    def __init__(self, enabled=False, start="23:00", end="06:00"):
        self.enabled = enabled
        self.start = start
        self.end = end

    def contains(self, minute):
        return self.enabled and Window(self.start, self.end).contains(minute)

    def to_dict(self):
        return {"enabled": self.enabled, "start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        return cls(data.get("enabled", False), data.get("start", "23:00"), data.get("end", "06:00"))


class Override:
    """„Jetzt anzeigen“: Ansicht ab `start` bis `until` (ISO-Zeitpunkte, `until` None = unbegrenzt)."""

    def __init__(self, view_id, start, until=None):
        self.view_id = view_id
        self.start = start
        self.until = until

    def to_dict(self):
        return {"view_id": self.view_id, "start": self.start, "until": self.until}

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(data["view_id"], data["start"], data.get("until"))


class Schedule:
    """Alle Ansichten samt Ruhezeit und manueller Anzeige."""

    def __init__(self, views=None, quiet=None, default_duration_minutes=10, override=None, migrated_from_playlists=False):
        self.views = list(views or [])
        self.quiet = quiet or QuietTime()
        self.default_duration_minutes = default_duration_minutes
        self.override = override
        self.migrated_from_playlists = migrated_from_playlists

    def get_view(self, view_id):
        return next((v for v in self.views if v.id == view_id), None)

    def find_view(self, plugin_id, name):
        return next((v for v in self.views if v.plugin_id == plugin_id and v.name == name), None)

    def rotation_views(self):
        return [v for v in self.views if v.rotation]

    def to_dict(self):
        return {
            "version": SCHEDULE_VERSION,
            "views": [v.to_dict() for v in self.views],
            "quiet": self.quiet.to_dict(),
            "default_duration_minutes": self.default_duration_minutes,
            "override": self.override.to_dict() if self.override else None,
            "migrated_from_playlists": self.migrated_from_playlists,
        }

    @classmethod
    def from_dict(cls, data):
        data = data or {}
        return cls(
            views=[View.from_dict(v) for v in data.get("views", [])],
            quiet=QuietTime.from_dict(data.get("quiet")),
            default_duration_minutes=data.get("default_duration_minutes", 10),
            override=Override.from_dict(data.get("override")),
            migrated_from_playlists=data.get("migrated_from_playlists", False),
        )


# ---------------------------------------------------------------------------
# Übernahme der alten Playlists
# ---------------------------------------------------------------------------

def _playlist_minutes(playlist):
    """Start/Ende einer Playlist in Minuten, wie im alten PlaylistManager."""
    start = parse_hm(playlist["start_time"])
    end = parse_hm(playlist["end_time"])
    return start, end


def _playlist_is_active(playlist, minute):
    start, end = _playlist_minutes(playlist)
    if start <= end:
        return start <= minute < end
    return minute >= start or minute < end


def _playlist_priority(playlist):
    start, end = _playlist_minutes(playlist)
    if end < start:
        end += MINUTES_PER_DAY
    return end - start


def active_playlist_by_minute(playlists):
    """Index der aktiven Playlist für jede Minute des Tages (None = keine).

    Bildet die alte Regel nach: unter den aktiven Playlists gewinnt die mit dem
    kürzesten Zeitfenster, bei Gleichstand die zuerst angelegte.
    """
    order = sorted(range(len(playlists)), key=lambda i: _playlist_priority(playlists[i]))
    result = []
    for minute in range(MINUTES_PER_DAY):
        result.append(next((i for i in order if _playlist_is_active(playlists[i], minute)), None))
    return result


def _windows_for(index, active):
    """Fasst die Minuten, in denen Playlist `index` aktiv ist, zu Zeiträumen zusammen."""
    runs = []
    minute = 0
    while minute < MINUTES_PER_DAY:
        if active[minute] == index:
            start = minute
            while minute < MINUTES_PER_DAY and active[minute] == index:
                minute += 1
            runs.append([start, minute])
        else:
            minute += 1
    # Zeitraum über Mitternacht (z. B. 21:00–03:00) wieder zusammenfügen
    if len(runs) > 1 and runs[0][0] == 0 and runs[-1][1] == MINUTES_PER_DAY:
        first = runs.pop(0)
        runs[-1][1] = first[1]
    return [Window(format_hm(s), format_hm(e)) for s, e in runs]


def migrate_from_playlists(playlist_config, plugin_cycle_interval_seconds=3600):
    """Erzeugt einen Zeitplan aus der bisherigen playlist_config.

    Zu jeder Minute kommen anschließend genau die Plugins in Frage, die bisher
    über die aktive Playlist gelaufen wären. Die Eingabe wird nicht verändert.
    """
    playlists = (playlist_config or {}).get("playlists", [])
    active = active_playlist_by_minute(playlists)
    duration = max(1, round(int(plugin_cycle_interval_seconds or 3600) / 60))

    views = []
    used_names = set()
    for index, playlist in enumerate(playlists):
        windows = _windows_for(index, active)
        never_active = not windows
        whole_day = len(windows) == 1 and windows[0].start == windows[0].end == "00:00"
        # Ganztägig aktiv braucht keine Einschränkung; nie aktiv heißt: nicht in der Rotation
        limit = None if whole_day or never_active else Limit(windows=windows)

        for plugin in playlist.get("plugins", []):
            name = plugin["name"]
            latest = plugin.get("latest_refresh_time")
            key = (plugin["plugin_id"], name)
            if key in used_names:
                # Gleiche Instanz in mehreren Playlists: eigener Name, damit die Bilder getrennt bleiben
                name = f"{name} ({playlist['name']})"
                latest = None
            used_names.add((plugin["plugin_id"], name))

            views.append(View(
                id=f"v{len(views) + 1}",
                plugin_id=plugin["plugin_id"],
                name=name,
                settings=dict(plugin.get("plugin_settings") or {}),
                rotation=not never_active,
                duration_minutes=duration,
                refresh=Refresh.from_playlist_refresh(plugin.get("refresh")),
                limit=Limit(windows=[Window(w.start, w.end) for w in limit.windows]) if limit else None,
                latest_refresh_time=latest,
            ))

    return Schedule(views=views, default_duration_minutes=min(duration, 60), migrated_from_playlists=True)
