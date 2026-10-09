import copy
import json
from datetime import date, datetime

import pytest

from src.model import PlaylistManager
from src.zeitplan import (
    FixedTime, Limit, Refresh, Schedule, View, Window, QuietTime, Override,
    migrate_from_playlists, parse_hm, format_hm,
)


def plugin(plugin_id, name, refresh=None, latest=None, settings=None):
    return {
        "plugin_id": plugin_id,
        "name": name,
        "plugin_settings": settings or {"stadt": "Berlin"},
        "refresh": refresh if refresh is not None else {"interval": 1800},
        "latest_refresh_time": latest,
    }


def playlist(name, start, end, plugins):
    return {"name": name, "start_time": start, "end_time": end, "plugins": plugins, "current_plugin_index": None}


def assert_same_as_playlists(config):
    """Für jede Minute: die Ansichten in der Rotation entsprechen genau den Plugins der alten aktiven Playlist."""
    manager = PlaylistManager.from_dict(copy.deepcopy(config))
    schedule = migrate_from_playlists(config)
    for minute in range(1440):
        current = datetime(2026, 10, 9, minute // 60, minute % 60)
        active = manager.determine_active_playlist(current)
        expected = sorted((p.plugin_id, p.name) for p in active.plugins) if active else []
        actual = sorted(
            (v.plugin_id, v.name.split(" (")[0]) for v in schedule.views
            if v.in_rotation_at(current.weekday(), minute)
        )
        assert actual == expected, f"Unterschied um {format_hm(minute)}"


class TestUhrzeiten:
    def test_parse_und_format(self):
        assert parse_hm("00:00") == 0
        assert parse_hm("07:30") == 450
        assert parse_hm("24:00") == 1440
        assert format_hm(450) == "07:30"
        assert format_hm(1440) == "00:00"

    def test_ungueltige_uhrzeit(self):
        with pytest.raises(ValueError):
            parse_hm("25:00")

    @pytest.mark.parametrize("start,end,minute,expected", [
        ("09:00", "15:00", "08:59", False),
        ("09:00", "15:00", "09:00", True),
        ("09:00", "15:00", "15:00", False),
        ("21:00", "03:00", "23:59", True),
        ("21:00", "03:00", "02:59", True),
        ("21:00", "03:00", "03:00", False),
        ("18:00", "00:00", "23:59", True),
        ("18:00", "24:00", "23:59", True),
        ("00:00", "00:00", "12:00", True),   # ganzer Tag
        ("12:00", "12:00", "12:00", False),  # leer
    ])
    def test_zeitraum(self, start, end, minute, expected):
        assert Window(start, end).contains(parse_hm(minute)) == expected


class TestFesteZeit:
    def test_woechentlich_mit_ausnahme(self):
        ft = FixedTime("f1", "06:30", "07:30", days=[0, 1, 2, 3, 4], except_dates=["2026-10-12"])
        assert ft.starts_on(date(2026, 10, 9))       # Freitag
        assert not ft.starts_on(date(2026, 10, 10))  # Samstag
        assert not ft.starts_on(date(2026, 10, 12))  # Montag, ausgesetzt
        assert ft.starts_on(date(2026, 10, 13))

    def test_einmalig(self):
        ft = FixedTime("f1", "18:00", "20:00", date="2026-12-24")
        assert ft.is_once
        assert ft.starts_on(date(2026, 12, 24))
        assert not ft.starts_on(date(2026, 12, 25))
        assert "days" not in ft.to_dict()

    def test_ende_um_mitternacht_und_ueber_mitternacht(self):
        assert FixedTime("a", "22:00", "00:00", days=[0]).end_minute() == 1440
        assert not FixedTime("a", "22:00", "00:00", days=[0]).wraps_midnight()
        assert FixedTime("b", "23:00", "01:00", days=[0]).wraps_midnight()


class TestSpeichern:
    def test_hin_und_zurueck(self):
        schedule = Schedule(
            views=[View(
                "v1", "weather", "Wetter Berlin", settings={"stadt": "Berlin"}, duration_minutes=10,
                refresh=Refresh("interval", minutes=15),
                limit=Limit(windows=[Window("17:00", "23:00")], days=[5, 6]),
                fixed_times=[FixedTime("f1", "08:00", "10:00", days=[5]), FixedTime("f2", "18:00", "19:00", date="2026-12-24")],
                latest_refresh_time="2026-10-09T08:00:00+02:00",
            )],
            quiet=QuietTime(True, "23:00", "06:00"),
            override=Override("v1", "2026-10-09T10:00:00+02:00", None),
        )
        data = json.loads(json.dumps(schedule.to_dict()))
        assert Schedule.from_dict(data).to_dict() == data

    def test_fehlende_felder_werden_ergaenzt(self):
        schedule = Schedule.from_dict({"views": [{"id": "v1", "plugin_id": "clock", "name": "Uhr"}]})
        view = schedule.views[0]
        assert view.rotation and view.limit is None and view.refresh.mode == "auto"
        assert not schedule.quiet.enabled and schedule.override is None

    def test_bildpfad_wie_bisher(self):
        assert View("v1", "weather", "Wetter Berlin").get_image_path() == "weather_Wetter_Berlin.png"


class TestUebernahmeAusPlaylists:
    def test_eine_ganztaegige_playlist(self):
        config = {"playlists": [playlist("Default", "00:00", "24:00", [
            plugin("weather", "Wetter", refresh={"interval": 900}, latest="2026-10-09T08:00:00"),
            plugin("calendar", "Kalender", refresh={"scheduled": "06:00"}),
        ])]}
        schedule = migrate_from_playlists(config, plugin_cycle_interval_seconds=1800)
        assert schedule.migrated_from_playlists
        assert [v.name for v in schedule.views] == ["Wetter", "Kalender"]
        wetter, kalender = schedule.views
        assert wetter.rotation and wetter.limit is None
        assert wetter.duration_minutes == 30
        assert wetter.refresh.to_dict() == {"mode": "interval", "minutes": 15}
        assert kalender.refresh.to_dict() == {"mode": "daily", "time": "06:00"}
        assert wetter.latest_refresh_time == "2026-10-09T08:00:00"
        assert wetter.settings == {"stadt": "Berlin"}
        assert schedule.default_duration_minutes == 30

    def test_kuerzere_playlist_verdraengt_ganztaegige(self):
        config = {"playlists": [
            playlist("Default", "00:00", "24:00", [plugin("weather", "Wetter")]),
            playlist("Morgen", "06:00", "09:00", [plugin("daily_dashboard", "Tagesübersicht")]),
        ]}
        schedule = migrate_from_playlists(config)
        wetter, morgen = schedule.views
        assert wetter.limit.windows == [Window("09:00", "06:00")]
        assert morgen.limit.windows == [Window("06:00", "09:00")]
        assert_same_as_playlists(config)

    def test_mehrere_zeitfenster(self):
        config = {"playlists": [
            playlist("Default", "00:00", "24:00", [plugin("weather", "Wetter"), plugin("calendar", "Kalender")]),
            playlist("Morgen", "06:00", "09:00", [plugin("daily_dashboard", "Tagesübersicht")]),
            playlist("Abend", "18:00", "22:00", [plugin("image_album", "Fotos")]),
            playlist("Nacht", "23:00", "05:00", [plugin("clock", "Uhr")]),
        ]}
        schedule = migrate_from_playlists(config)
        wetter = schedule.find_view("weather", "Wetter")
        assert wetter.limit.windows == [Window("05:00", "06:00"), Window("09:00", "18:00"), Window("22:00", "23:00")]
        assert schedule.find_view("clock", "Uhr").limit.windows == [Window("23:00", "05:00")]
        assert_same_as_playlists(config)

    def test_ueberlappende_playlists(self):
        config = {"playlists": [
            playlist("Tag", "07:00", "20:00", [plugin("weather", "Wetter")]),
            playlist("Mittag", "11:00", "14:00", [plugin("calendar", "Kalender")]),
            playlist("Spät", "12:00", "22:00", [plugin("rss", "News")]),
        ]}
        assert_same_as_playlists(config)

    def test_leere_playlist_blockiert_wie_bisher(self):
        config = {"playlists": [
            playlist("Default", "00:00", "24:00", [plugin("weather", "Wetter")]),
            playlist("Pause", "12:00", "13:00", []),
        ]}
        schedule = migrate_from_playlists(config)
        assert len(schedule.views) == 1
        assert not schedule.views[0].in_rotation_at(0, parse_hm("12:30"))
        assert_same_as_playlists(config)

    def test_nie_aktive_playlist(self):
        config = {"playlists": [
            playlist("Default", "00:00", "24:00", [plugin("weather", "Wetter")]),
            playlist("Kaputt", "10:00", "10:00", [plugin("clock", "Uhr")]),
        ]}
        schedule = migrate_from_playlists(config)
        uhr = schedule.find_view("clock", "Uhr")
        assert uhr is not None and not uhr.rotation
        assert_same_as_playlists(config)

    def test_gleiche_instanz_in_zwei_playlists(self):
        config = {"playlists": [
            playlist("Default", "00:00", "24:00", [plugin("weather", "Wetter", latest="2026-10-09T08:00:00")]),
            playlist("Abend", "18:00", "22:00", [plugin("weather", "Wetter", latest="2026-10-09T19:00:00")]),
        ]}
        schedule = migrate_from_playlists(config)
        names = [v.name for v in schedule.views]
        assert names == ["Wetter", "Wetter (Abend)"]
        assert len({v.get_image_path() for v in schedule.views}) == 2
        assert schedule.views[1].latest_refresh_time is None
        assert_same_as_playlists(config)

    def test_eingabe_bleibt_unveraendert(self):
        config = {"playlists": [playlist("Default", "00:00", "24:00", [plugin("weather", "Wetter")])]}
        before = copy.deepcopy(config)
        schedule = migrate_from_playlists(config)
        schedule.views[0].settings["stadt"] = "Hamburg"
        assert config == before

    def test_keine_playlists(self):
        schedule = migrate_from_playlists({})
        assert schedule.views == []
        assert migrate_from_playlists(None).views == []

    def test_ids_sind_eindeutig(self):
        config = {"playlists": [
            playlist("A", "00:00", "24:00", [plugin("weather", "W1"), plugin("weather", "W2")]),
            playlist("B", "08:00", "09:00", [plugin("clock", "Uhr")]),
        ]}
        ids = [v.id for v in migrate_from_playlists(config).views]
        assert len(ids) == len(set(ids))


class TestKonfiguration:
    @pytest.fixture
    def config(self, tmp_path, monkeypatch):
        pytest.importorskip("dotenv")
        from pathlib import Path
        monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent.parent / "src"))
        from config import Config
        from model import RefreshInfo

        device = {
            "name": "InkyPi",
            "plugin_cycle_interval_seconds": 600,
            "playlist_config": {"playlists": [playlist("Default", "00:00", "24:00", [plugin("weather", "Wetter")])], "active_playlist": None},
            "refresh_info": {},
        }
        path = tmp_path / "device.json"
        path.write_text(json.dumps(device))
        cfg = Config.__new__(Config)
        cfg.config_file = str(path)
        cfg.config = cfg.read_config()
        cfg.playlist_manager = cfg.load_playlist_manager()
        cfg.refresh_info = RefreshInfo.from_dict({})
        return cfg, path

    def test_laden_ohne_gespeicherten_zeitplan_schreibt_nichts(self, config):
        cfg, path = config
        before = path.read_text()
        schedule = cfg.load_schedule()
        assert [v.name for v in schedule.views] == ["Wetter"]
        assert schedule.views[0].duration_minutes == 10
        assert path.read_text() == before
        assert list(path.parent.glob("device.json.bak-*")) == []

    def test_speichern_sichert_einmal_und_behaelt_playlists(self, config):
        cfg, path = config
        original = json.loads(path.read_text())
        schedule = cfg.load_schedule()
        schedule.quiet.enabled = True
        cfg.save_schedule(schedule)
        cfg.save_schedule(schedule)

        backups = list(path.parent.glob("device.json.bak-vor-zeitplan-*"))
        assert len(backups) == 1
        assert json.loads(backups[0].read_text()) == original

        saved = json.loads(path.read_text())
        assert saved["playlist_config"]["playlists"][0]["plugins"][0]["name"] == "Wetter"
        assert saved["schedule"]["quiet"]["enabled"] is True
        assert cfg.load_schedule().quiet.enabled
