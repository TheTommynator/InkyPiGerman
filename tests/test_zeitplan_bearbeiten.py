import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from zeitplan import FixedTime, Override, Schedule, View  # noqa: E402
from zeitplan_bearbeiten import (  # noqa: E402
    ScheduleError, apply_update, check_view_name, describe_fixed, schedule_for_page,
)


def zeitplan():
    return Schedule(
        views=[
            View("w", "weather", "Wetter", settings={"stadt": "Berlin"}, latest_refresh_time="2026-10-10T08:00:00"),
            View("t", "daily_dashboard", "Tagesübersicht", rotation=False,
                 fixed_times=[FixedTime("f1", "06:30", "07:30", days=[0, 1, 2, 3, 4])]),
        ],
        override=Override("w", "2026-10-10T08:00:00", None),
    )


def payload(schedule, **changes):
    data = schedule_for_page(schedule)
    for view in data["views"]:
        view.update(changes.get(view["id"], {}))
    data.update(changes.get("_", {}))
    return data


def test_unveraendert_bleibt_gleich():
    schedule = zeitplan()
    result, renames = apply_update(schedule, payload(schedule))
    assert result.to_dict() == schedule.to_dict()
    assert renames == []


def test_einstellungen_und_letzte_aktualisierung_bleiben_erhalten():
    schedule = zeitplan()
    result, _ = apply_update(schedule, payload(schedule, w={"duration_minutes": 15, "refresh": {"mode": "interval", "minutes": 15}}))
    wetter = result.get_view("w")
    assert wetter.settings == {"stadt": "Berlin"}
    assert wetter.latest_refresh_time == "2026-10-10T08:00:00"
    assert wetter.duration_minutes == 15
    assert wetter.refresh.to_dict() == {"mode": "interval", "minutes": 15}
    assert result.override.view_id == "w"


def test_reihenfolge_folgt_der_seite():
    schedule = zeitplan()
    data = payload(schedule)
    data["views"].reverse()
    result, _ = apply_update(schedule, data)
    assert [v.id for v in result.views] == ["t", "w"]


def test_umbenennen_meldet_bilddatei():
    schedule = zeitplan()
    _, renames = apply_update(schedule, payload(schedule, w={"name": "Wetter Berlin"}))
    assert renames == [("weather_Wetter.png", "weather_Wetter_Berlin.png")]


def test_feste_zeit_ohne_id_bekommt_eine():
    schedule = zeitplan()
    result, _ = apply_update(schedule, payload(schedule, w={"fixed_times": [{"start": "08:00", "end": "10:00", "days": [5]}]}))
    assert result.get_view("w").fixed_times[0].id.startswith("f")


def test_einschraenkung_ganz_ohne_grenzen_entfaellt():
    schedule = zeitplan()
    result, _ = apply_update(schedule, payload(schedule, w={"limit": {"windows": [], "days": [0, 1, 2, 3, 4, 5, 6]}}))
    assert result.get_view("w").limit is None
    result, _ = apply_update(schedule, payload(schedule, w={"limit": {"windows": [{"start": "17:00", "end": "23:00"}], "days": [5, 6]}}))
    assert result.get_view("w").limit.days == [5, 6]


def test_ruhezeit_und_standarddauer():
    schedule = zeitplan()
    result, _ = apply_update(schedule, payload(schedule, _={"quiet": {"enabled": True, "start": "22:30", "end": "06:00"}, "default_duration_minutes": 15}))
    assert result.quiet.to_dict() == {"enabled": True, "start": "22:30", "end": "06:00"}
    assert result.default_duration_minutes == 15


@pytest.mark.parametrize("changes,message", [
    ({"w": {"name": "  "}}, "Namen"),
    ({"w": {"name": "Tagesübersicht"}}, "schon eine Ansicht"),
    ({"w": {"name": "Wetter/Berlin"}}, "nur Buchstaben"),
    ({"w": {"duration_minutes": 0}}, "Anzeigedauer"),
    ({"w": {"refresh": {"mode": "interval", "minutes": "x"}}}, "Aktualisierung"),
    ({"w": {"limit": {"windows": [{"start": "10:00", "end": "10:00"}]}}}, "Start und Ende"),
    ({"w": {"limit": {"windows": [], "days": []}}}, "Wochentag"),
    ({"w": {"fixed_times": [{"start": "25:00", "end": "10:00", "days": [1]}]}}, "Uhrzeit"),
    ({"w": {"fixed_times": [{"start": "08:00", "end": "09:00", "days": []}]}}, "Wochentag"),
    ({"w": {"fixed_times": [{"start": "08:00", "end": "09:00", "date": "2026-13-01"}]}}, "Datum"),
    ({"_": {"quiet": {"enabled": True, "start": "06:00", "end": "06:00"}}}, "Ruhezeit"),
])
def test_ungueltige_eingaben(changes, message):
    schedule = zeitplan()
    with pytest.raises(ScheduleError, match=message):
        apply_update(schedule, payload(schedule, **changes))


def test_ueberschneidung_wird_abgelehnt():
    schedule = zeitplan()
    data = payload(schedule, w={"fixed_times": [{"id": "neu", "start": "07:00", "end": "08:00", "days": [4]}]})
    with pytest.raises(ScheduleError) as error:
        apply_update(schedule, data)
    assert "„Wetter“ (Fr 07:00–08:00)" in str(error.value)
    assert "„Tagesübersicht“ (Mo–Fr 06:30–07:30)" in str(error.value)


def test_veralteter_stand_wird_abgelehnt():
    schedule = zeitplan()
    data = payload(schedule)
    data["views"].pop()
    with pytest.raises(ScheduleError, match="neu"):
        apply_update(schedule, data)


def test_seite_bekommt_keine_plugin_einstellungen():
    data = schedule_for_page(zeitplan())
    assert all("settings" not in v for v in data["views"])


def test_name_pruefen():
    schedule = zeitplan()
    assert check_view_name("  Wetter (Abend) ", schedule) == "Wetter (Abend)"
    assert check_view_name("Wetter", schedule, ignore_id="w") == "Wetter"
    with pytest.raises(ScheduleError):
        check_view_name("wetter", schedule)


def test_beschreibung_fester_zeiten():
    assert describe_fixed(FixedTime("a", "22:00", "00:00", days=[5, 6])) == "Sa, So 22:00–24:00"
    assert describe_fixed(FixedTime("b", "18:00", "20:00", date="2026-12-24")) == "24.12.2026 18:00–20:00"
