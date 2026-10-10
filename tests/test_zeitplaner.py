import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from zeitplan import (  # noqa: E402
    FixedTime, Limit, Override, QuietTime, Refresh, Schedule, View, Window,
)
from zeitplaner import (  # noqa: E402
    KIND_FIXED, KIND_IDLE, KIND_OVERRIDE, KIND_QUIET, KIND_ROTATION, Segment,
    all_conflicts, current_segment, find_conflict, fixed_times_overlap, needs_refresh,
    next_refresh_at, next_wakeup, plan_day, retry_at, upcoming_segments,
)

FREITAG = date(2026, 10, 9)
SAMSTAG = date(2026, 10, 10)
SONNTAG = date(2026, 10, 11)
WERKTAGE = [0, 1, 2, 3, 4]


def at(day, hm):
    hour, minute = map(int, hm.split(":"))
    return datetime(day.year, day.month, day.day) + timedelta(hours=hour, minutes=minute)


def view(id, name, duration=10, rotation=True, limit=None, fixed=None, refresh=None, plugin_id="weather", latest=None):
    return View(id, plugin_id, name, rotation=rotation, duration_minutes=duration, limit=limit,
                fixed_times=fixed or [], refresh=refresh, latest_refresh_time=latest)


def summary(segments):
    return [(s.kind, f"{s.start:%H:%M}", "24:00" if s.end.time() == datetime.min.time() and s.end > s.start else f"{s.end:%H:%M}",
             s.view.name if s.view else None) for s in segments]


def assert_covers_day(segments, day):
    assert segments[0].start == at(day, "00:00")
    assert segments[-1].end == at(day, "00:00") + timedelta(days=1)
    for before, after in zip(segments, segments[1:]):
        assert before.end == after.start
        assert before.start < before.end


class TestRotation:
    def test_eigene_anzeigedauer_und_reihenfolge(self):
        schedule = Schedule(views=[view("a", "A", 10), view("b", "B", 15), view("c", "C", 5)])
        segments = plan_day(schedule, FREITAG)
        assert_covers_day(segments, FREITAG)
        assert summary(segments[:4]) == [
            (KIND_ROTATION, "00:00", "00:10", "A"),
            (KIND_ROTATION, "00:10", "00:25", "B"),
            (KIND_ROTATION, "00:25", "00:30", "C"),
            (KIND_ROTATION, "00:30", "00:40", "A"),
        ]

    def test_wechsel_liegen_auf_der_uhr(self):
        schedule = Schedule(views=[view("a", "A", 15), view("b", "B", 15)], quiet=QuietTime(True, "23:00", "06:00"))
        segments = plan_day(schedule, FREITAG)
        rotation = [s for s in segments if s.kind == KIND_ROTATION]
        assert all(s.start.minute % 15 == 0 for s in rotation)
        assert rotation[0].start == at(FREITAG, "06:00") and rotation[0].view.name == "A"

    def test_rotation_beginnt_jeden_tag_mit_der_ersten_ansicht(self):
        schedule = Schedule(views=[view("a", "A", 7), view("b", "B", 11)])
        for day in (FREITAG, SAMSTAG, SONNTAG):
            assert plan_day(schedule, day)[0].view.name == "A"

    def test_nicht_in_rotation(self):
        schedule = Schedule(views=[view("a", "A"), view("b", "B", rotation=False)])
        assert {s.view.name for s in plan_day(schedule, FREITAG)} == {"A"}

    def test_einschraenkung_auf_zeitraum_und_tage(self):
        fotos = view("f", "Fotos", 5, limit=Limit(windows=[Window("17:00", "23:00")], days=[5, 6]))
        schedule = Schedule(views=[view("w", "Wetter", 10), fotos])
        friday = plan_day(schedule, FREITAG)
        saturday = plan_day(schedule, SAMSTAG)
        assert not any(s.view is fotos for s in friday)
        fotos_slots = [s for s in saturday if s.view is fotos]
        assert fotos_slots and all(at(SAMSTAG, "17:00") <= s.start and s.end <= at(SAMSTAG, "23:00") for s in fotos_slots)

    def test_abschnitt_endet_wenn_zeitraum_endet(self):
        abend = view("a", "Abend", 60, limit=Limit(windows=[Window("17:30", "18:10")]))
        schedule = Schedule(views=[abend])
        segments = [s for s in plan_day(schedule, FREITAG) if s.kind == KIND_ROTATION]
        assert summary(segments) == [(KIND_ROTATION, "17:30", "18:10", "Abend")]

    def test_nichts_geplant(self):
        schedule = Schedule(views=[view("a", "A", limit=Limit(windows=[Window("08:00", "09:00")]))])
        segments = plan_day(schedule, FREITAG)
        assert_covers_day(segments, FREITAG)
        assert summary([segments[0], segments[-1]]) == [(KIND_IDLE, "00:00", "08:00", None), (KIND_IDLE, "09:00", "24:00", None)]

    def test_leerer_zeitplan(self):
        segments = plan_day(Schedule(), FREITAG)
        assert summary(segments) == [(KIND_IDLE, "00:00", "24:00", None)]


class TestRuhezeit:
    def test_ueber_mitternacht(self):
        schedule = Schedule(views=[view("a", "A", 30)], quiet=QuietTime(True, "23:00", "06:00"))
        segments = plan_day(schedule, FREITAG)
        assert_covers_day(segments, FREITAG)
        assert summary([segments[0], segments[-1]]) == [(KIND_QUIET, "00:00", "06:00", None), (KIND_QUIET, "23:00", "24:00", None)]

    def test_ausgeschaltet(self):
        schedule = Schedule(views=[view("a", "A")], quiet=QuietTime(False, "23:00", "06:00"))
        assert not any(s.kind == KIND_QUIET for s in plan_day(schedule, FREITAG))


class TestFesteZeiten:
    def schedule(self, fixed, quiet=None):
        return Schedule(
            views=[view("w", "Wetter", 20), view("t", "Tagesübersicht", rotation=False, fixed=[fixed])],
            quiet=quiet or QuietTime(True, "23:00", "06:00"),
        )

    def test_unterbricht_rotation_auf_die_minute(self):
        segments = plan_day(self.schedule(FixedTime("f", "06:30", "07:30", days=WERKTAGE)), FREITAG)
        assert_covers_day(segments, FREITAG)
        assert (KIND_ROTATION, "06:20", "06:30", "Wetter") in summary(segments)
        assert (KIND_FIXED, "06:30", "07:30", "Tagesübersicht") in summary(segments)
        assert (KIND_ROTATION, "07:30", "07:50", "Wetter") in summary(segments)

    def test_nur_an_den_gewaehlten_tagen(self):
        segments = plan_day(self.schedule(FixedTime("f", "06:30", "07:30", days=WERKTAGE)), SAMSTAG)
        assert not any(s.kind == KIND_FIXED for s in segments)

    def test_hat_vorrang_vor_ruhezeit(self):
        segments = plan_day(self.schedule(FixedTime("f", "05:00", "06:30", days=WERKTAGE)), FREITAG)
        assert summary(segments[:3]) == [
            (KIND_QUIET, "00:00", "05:00", None),
            (KIND_FIXED, "05:00", "06:30", "Tagesübersicht"),
            (KIND_ROTATION, "06:30", "06:50", "Wetter"),
        ]

    def test_ueber_mitternacht(self):
        schedule = self.schedule(FixedTime("f", "23:00", "01:00", days=[4]))  # Freitag
        friday, saturday, sunday = (plan_day(schedule, d) for d in (FREITAG, SAMSTAG, SONNTAG))
        assert summary(friday)[-1] == (KIND_FIXED, "23:00", "24:00", "Tagesübersicht")
        assert summary(saturday)[0] == (KIND_FIXED, "00:00", "01:00", "Tagesübersicht")
        assert summary(sunday)[0] == (KIND_QUIET, "00:00", "06:00", None)

    def test_ende_um_mitternacht(self):
        schedule = self.schedule(FixedTime("f", "22:00", "00:00", days=[4]))
        assert summary(plan_day(schedule, FREITAG))[-1] == (KIND_FIXED, "22:00", "24:00", "Tagesübersicht")
        assert summary(plan_day(schedule, SAMSTAG))[0] == (KIND_QUIET, "00:00", "06:00", None)

    def test_ausgesetzter_tag(self):
        schedule = self.schedule(FixedTime("f", "06:30", "07:30", days=WERKTAGE, except_dates=["2026-10-09"]))
        assert not any(s.kind == KIND_FIXED for s in plan_day(schedule, FREITAG))
        assert any(s.kind == KIND_FIXED for s in plan_day(schedule, date(2026, 10, 12)))

    def test_einmalig(self):
        schedule = self.schedule(FixedTime("f", "18:00", "20:00", date="2026-12-24"))
        assert not any(s.kind == KIND_FIXED for s in plan_day(schedule, FREITAG))
        assert (KIND_FIXED, "18:00", "20:00", "Tagesübersicht") in summary(plan_day(schedule, date(2026, 12, 24)))


class TestManuell:
    def schedule(self, start, until):
        return Schedule(
            views=[view("w", "Wetter", 20), view("t", "Tagesübersicht", rotation=False,
                                                 fixed=[FixedTime("f", "06:30", "07:30", days=WERKTAGE)])],
            override=Override("w", start, until),
        )

    def test_hat_vorrang_vor_fester_zeit(self):
        segments = plan_day(self.schedule("2026-10-09T06:00:00", "2026-10-09T07:00:00"), FREITAG)
        assert (KIND_OVERRIDE, "06:00", "07:00", "Wetter") in summary(segments)
        assert (KIND_FIXED, "07:00", "07:30", "Tagesübersicht") in summary(segments)

    def test_beginnt_mitten_in_fester_zeit(self):
        segments = plan_day(self.schedule("2026-10-09T07:00:00", "2026-10-09T08:00:00"), FREITAG)
        assert_covers_day(segments, FREITAG)
        assert (KIND_FIXED, "06:30", "07:00", "Tagesübersicht") in summary(segments)
        assert (KIND_OVERRIDE, "07:00", "08:00", "Wetter") in summary(segments)

    def test_ohne_ende_gilt_auch_an_folgetagen(self):
        schedule = self.schedule("2026-10-09T12:00:00", None)
        assert summary(plan_day(schedule, FREITAG))[-1] == (KIND_OVERRIDE, "12:00", "24:00", "Wetter")
        assert summary(plan_day(schedule, SAMSTAG)) == [(KIND_OVERRIDE, "00:00", "24:00", "Wetter")]

    def test_ende_mitten_in_der_minute(self):
        segments = plan_day(self.schedule("2026-10-09T10:00:00", "2026-10-09T11:00:30"), FREITAG)
        assert_covers_day(segments, FREITAG)
        assert (KIND_OVERRIDE, "10:00", "11:01", "Wetter") in summary(segments)

    def test_zeitpunkte_mit_zeitzone(self):
        tz = timezone(timedelta(hours=2))
        schedule = self.schedule(datetime(2026, 10, 9, 9, 0, tzinfo=tz).isoformat(), datetime(2026, 10, 9, 10, 0, tzinfo=tz).isoformat())
        assert (KIND_OVERRIDE, "09:00", "10:00", "Wetter") in summary(plan_day(schedule, FREITAG))

    def test_geloeschte_ansicht_wird_ignoriert(self):
        schedule = self.schedule("2026-10-09T06:00:00", None)
        schedule.override = Override("gibt-es-nicht", "2026-10-09T06:00:00", None)
        assert not any(s.kind == KIND_OVERRIDE for s in plan_day(schedule, FREITAG))


class TestAktuellUndAlsNaechstes:
    def test_current_und_upcoming_ueber_mitternacht(self):
        schedule = Schedule(views=[view("w", "Wetter", 30)], quiet=QuietTime(True, "23:00", "06:00"))
        now = at(FREITAG, "22:50")
        assert summary([current_segment(schedule, now)]) == [(KIND_ROTATION, "22:30", "23:00", "Wetter")]
        nxt = upcoming_segments(schedule, now, 3)
        assert [s.kind for s in nxt] == [KIND_QUIET, KIND_QUIET, KIND_ROTATION]
        assert nxt[1].start == at(SAMSTAG, "00:00")
        assert nxt[2].start == at(SAMSTAG, "06:00")


class TestAktualisierung:
    def segment(self, start="08:00", end="10:00", day=SAMSTAG):
        return Segment(KIND_FIXED, at(day, start), at(day, end))

    def test_alle_15_minuten_waehrend_langer_anzeige(self):
        wetter = view("w", "Wetter", refresh=Refresh("interval", minutes=15), latest="2026-10-10T08:00:00")
        seg = self.segment()
        assert not needs_refresh(wetter, at(SAMSTAG, "08:10"), seg)
        assert needs_refresh(wetter, at(SAMSTAG, "08:15"), seg)
        assert next_refresh_at(wetter, at(SAMSTAG, "08:10"), seg) == at(SAMSTAG, "08:15")
        wetter.latest_refresh_time = "2026-10-10T09:45:00"
        assert next_refresh_at(wetter, at(SAMSTAG, "09:50"), seg) is None  # 10:00 ist schon der nächste Abschnitt

    def test_automatisch_nach_plugin(self):
        wetter = view("w", "Wetter", refresh=Refresh("auto"), latest="2026-10-10T08:00:00")
        seg = self.segment()
        assert not needs_refresh(wetter, at(SAMSTAG, "08:29"), seg)
        assert needs_refresh(wetter, at(SAMSTAG, "08:30"), seg)

    def test_nur_beim_einblenden(self):
        fotos = view("f", "Fotos", plugin_id="image_album", refresh=Refresh("on_show"), latest="2026-10-10T07:55:00")
        seg = self.segment()
        assert needs_refresh(fotos, at(SAMSTAG, "08:00"), seg)
        fotos.latest_refresh_time = "2026-10-10T08:00:00"
        assert not needs_refresh(fotos, at(SAMSTAG, "09:59"), seg)
        assert next_refresh_at(fotos, at(SAMSTAG, "08:00"), seg) is None

    def test_taeglich(self):
        kalender = view("k", "Kalender", refresh=Refresh("daily", time="06:00"), latest="2026-10-09T06:05:00")
        seg = self.segment("00:00", "23:00")
        assert not needs_refresh(kalender, at(SAMSTAG, "05:59"), seg)
        assert needs_refresh(kalender, at(SAMSTAG, "06:00"), seg)
        kalender.latest_refresh_time = "2026-10-10T06:01:00"
        assert not needs_refresh(kalender, at(SAMSTAG, "22:00"), seg)

    def test_ohne_bisherige_daten(self):
        assert needs_refresh(view("w", "Wetter"), at(SAMSTAG, "08:00"), self.segment())

    def test_zeitstempel_mit_zeitzone(self):
        wetter = view("w", "Wetter", refresh=Refresh("interval", minutes=15),
                      latest=datetime(2026, 10, 10, 8, 0, tzinfo=timezone(timedelta(hours=2))).isoformat())
        assert not needs_refresh(wetter, at(SAMSTAG, "08:10"), self.segment())

    def test_naechstes_aufwachen(self):
        wetter = view("w", "Wetter", rotation=False, refresh=Refresh("interval", minutes=15), latest="2026-10-10T08:00:00",
                      fixed=[FixedTime("f", "08:00", "10:00", days=[5])])
        schedule = Schedule(views=[view("k", "Kalender", 60, plugin_id="calendar", latest="2026-10-10T07:10:00"), wetter])
        assert next_wakeup(schedule, at(SAMSTAG, "08:05")) == at(SAMSTAG, "08:15")
        assert next_wakeup(schedule, at(SAMSTAG, "07:20")) == at(SAMSTAG, "07:25")  # Kalender: alle 15 Min
        schedule.views[0].latest_refresh_time = "2026-10-10T06:50:00"
        assert next_wakeup(schedule, at(SAMSTAG, "07:20")) == at(SAMSTAG, "07:20")  # überfällig: sofort
        wetter.latest_refresh_time = "2026-10-10T09:50:00"
        assert next_wakeup(schedule, at(SAMSTAG, "09:55")) == at(SAMSTAG, "10:00")

    def test_neuer_versuch_nach_fehler(self):
        seg = self.segment()
        assert retry_at(at(SAMSTAG, "08:10"), seg) == at(SAMSTAG, "08:15")
        assert retry_at(at(SAMSTAG, "09:57"), seg) is None


class TestUeberschneidungen:
    @pytest.mark.parametrize("a,b,expected", [
        (FixedTime("1", "06:30", "07:30", days=WERKTAGE), FixedTime("2", "07:00", "08:00", days=[4]), True),
        (FixedTime("1", "06:30", "07:30", days=WERKTAGE), FixedTime("2", "07:00", "08:00", days=[5, 6]), False),
        (FixedTime("1", "06:30", "07:30", days=WERKTAGE), FixedTime("2", "07:30", "08:00", days=WERKTAGE), False),  # direkt anschließend
        (FixedTime("1", "23:00", "01:00", days=[4]), FixedTime("2", "00:30", "02:00", days=[5]), True),  # Fr-Nacht in den Samstag
        (FixedTime("1", "23:00", "01:00", days=[4]), FixedTime("2", "00:30", "02:00", days=[4]), False),
        (FixedTime("1", "08:00", "10:00", days=[5]), FixedTime("2", "09:00", "11:00", date="2026-10-10"), True),
        (FixedTime("1", "08:00", "10:00", days=[5], except_dates=["2026-10-10"]), FixedTime("2", "09:00", "11:00", date="2026-10-10"), False),
        (FixedTime("1", "08:00", "10:00", date="2026-10-10"), FixedTime("2", "09:00", "11:00", date="2026-10-11"), False),
        (FixedTime("1", "08:00", "10:00", date="2026-10-10"), FixedTime("2", "09:00", "11:00", date="2026-10-10"), True),
        (FixedTime("1", "22:00", "00:00", days=[4]), FixedTime("2", "00:00", "01:00", days=[5]), False),
    ])
    def test_ueberschneidung(self, a, b, expected):
        assert fixed_times_overlap(a, b) == expected
        assert fixed_times_overlap(b, a) == expected

    def test_find_und_all_conflicts(self):
        neu = FixedTime("neu", "07:00", "08:00", days=[4])
        schedule = Schedule(views=[
            view("t", "Tagesübersicht", fixed=[FixedTime("f1", "06:30", "07:30", days=WERKTAGE)]),
            view("z", "Zeitung", fixed=[FixedTime("f2", "08:00", "10:00", days=[6])]),
        ])
        conflict_view, conflict_fixed = find_conflict(schedule, neu)
        assert conflict_view.name == "Tagesübersicht" and conflict_fixed.id == "f1"
        assert find_conflict(schedule, schedule.views[0].fixed_times[0]) is None  # eigene feste Zeit zählt nicht
        assert all_conflicts(schedule) == []
        schedule.views[1].fixed_times.append(neu)
        assert len(all_conflicts(schedule)) == 1


def test_tagesplan_ist_schnell_genug_fuer_den_pi():
    views = [view(f"v{i}", f"Ansicht {i}", 5 + i % 4 * 5, limit=Limit(windows=[Window("06:00", "22:00")]) if i % 3 else None,
                  fixed=[FixedTime(f"f{i}", f"{8 + i:02d}:00", f"{8 + i:02d}:30", days=WERKTAGE)] if i < 8 else [])
             for i in range(20)]
    schedule = Schedule(views=views, quiet=QuietTime(True, "23:00", "06:00"))
    started = time.perf_counter()
    segments = plan_day(schedule, FREITAG)
    assert time.perf_counter() - started < 1.0
    assert_covers_day(segments, FREITAG)
