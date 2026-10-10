import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

for module in ("PIL", "psutil", "pytz"):
    pytest.importorskip(module)

from PIL import Image  # noqa: E402
import refresh_task as rt  # noqa: E402
from model import RefreshInfo  # noqa: E402


class FakeConfig:
    def __init__(self):
        self.refresh_info = RefreshInfo(None, None, None, None)
        self.writes = 0

    def get_config(self, key=None, default={}):
        return {"timezone": "UTC", "plugin_cycle_interval_seconds": 3600}.get(key, default)

    def get_playlist_manager(self):
        return None

    def get_refresh_info(self):
        return self.refresh_info

    def get_plugin(self, plugin_id):
        return {"id": plugin_id} if plugin_id != "fehlt" else None

    def write_config(self):
        self.writes += 1

    def is_schedule_active(self):
        return False


class FakePlugin:
    config = {}

    def generate_image(self, settings, device_config):
        return Image.new("RGB", (10, 10), settings.get("farbe", "white"))


class SlowDisplay:
    """Hält den Bildaufbau an, bis der Test ihn freigibt."""

    def __init__(self, fail=False):
        self.started = threading.Event()
        self.release = threading.Event()
        self.shown = []
        self.fail = fail

    def display_image(self, image, image_settings=[]):
        self.started.set()
        self.release.wait(5)
        if self.fail:
            raise RuntimeError("Display kaputt")
        self.shown.append(image.getpixel((0, 0)))


@pytest.fixture
def task(monkeypatch):
    monkeypatch.setattr(rt, "get_plugin_instance", lambda config: FakePlugin())
    created = []

    def make(display):
        t = rt.RefreshTask(FakeConfig(), display)
        t.start()
        created.append((t, display))
        return t

    yield make
    for t, display in created:
        display.release.set()
        t.stop()


def test_manuelles_update_wartet_nicht_auf_das_display(task):
    display = SlowDisplay()
    t = task(display)

    assert t.manual_update(rt.ManualRefresh("bild", {"farbe": "red"})) is True
    # Antwort ist da, obwohl das Display noch aufbaut
    assert display.started.wait(5)
    assert display.shown == []
    display.release.set()


def test_zweites_update_waehrend_des_bildaufbaus(task):
    display = SlowDisplay()
    t = task(display)
    t.manual_update(rt.ManualRefresh("bild", {"farbe": "red"}))
    assert display.started.wait(5)

    result = {}
    worker = threading.Thread(target=lambda: result.update(
        started=t.manual_update(rt.ManualRefresh("bild", {"farbe": "blue"}))))
    worker.start()
    display.release.set()
    worker.join(5)
    assert result["started"] is True

    t.stop()
    assert display.shown == [(255, 0, 0), (0, 0, 255)]


def test_gleiches_bild_wird_nicht_erneut_angezeigt(task):
    display = SlowDisplay()
    display.release.set()
    t = task(display)
    assert t.manual_update(rt.ManualRefresh("bild", {})) is True
    assert t.manual_update(rt.ManualRefresh("bild", {})) is False


def test_fehler_beim_erzeugen_landet_bei_der_anfrage(task):
    t = task(SlowDisplay())
    with pytest.raises(ValueError):
        t.manual_update(rt.ManualRefresh("fehlt", {}))


def test_displayfehler_setzt_den_bildstand_zurueck(task):
    display = SlowDisplay(fail=True)
    display.release.set()
    t = task(display)
    t.manual_update(rt.ManualRefresh("bild", {}))
    t.stop()
    # Beim nächsten Mal wird das Bild erneut gesendet statt übersprungen
    assert t.device_config.refresh_info.image_hash is None


# --- Zeitplan (Beta) ---------------------------------------------------------

from datetime import datetime  # noqa: E402
from zeitplan import FixedTime, Refresh, Schedule, View  # noqa: E402

JETZT = datetime(2026, 10, 10, 8, 5)  # Samstag


class ScheduleConfig(FakeConfig):
    def __init__(self, tmp_path, schedule):
        super().__init__()
        self.schedule = schedule
        self.plugin_image_dir = str(tmp_path)

    def is_schedule_active(self):
        return True

    def get_schedule(self):
        return self.schedule


class FailingPlugin(FakePlugin):
    def generate_image(self, settings, device_config):
        raise RuntimeError("Wetterdienst nicht erreichbar")


def wetter_zeitplan(latest=None):
    wetter = View("w", "weather", "Wetter Berlin", settings={"farbe": "blue"}, rotation=False,
                  refresh=Refresh("interval", minutes=15), latest_refresh_time=latest,
                  fixed_times=[FixedTime("f", "08:00", "10:00", days=[5])])
    kalender = View("k", "calendar", "Kalender", settings={"farbe": "red"}, duration_minutes=30)
    return Schedule(views=[kalender, wetter])


@pytest.fixture
def schedule_task(monkeypatch, tmp_path):
    def make(schedule, plugin=None, now=JETZT):
        monkeypatch.setattr(rt, "get_plugin_instance", lambda config: plugin or FakePlugin())
        t = rt.RefreshTask(ScheduleConfig(tmp_path, schedule), SlowDisplay())
        t.display_manager.release.set()
        monkeypatch.setattr(t, "_get_current_datetime", lambda: now)
        return t
    return make


def test_zeitplan_bestimmt_die_ansicht(schedule_task):
    t = schedule_task(wetter_zeitplan())
    action = t._determine_view_refresh(JETZT)
    assert action.view.name == "Wetter Berlin"
    assert action.segment.kind == "fixed"


def test_zeitplan_ruhezeit_zeigt_nichts(schedule_task):
    schedule = wetter_zeitplan()
    schedule.quiet.enabled = True
    night = datetime(2026, 10, 10, 2, 0)
    t = schedule_task(schedule, now=night)
    assert t._determine_view_refresh(night) is None


def test_zeitplan_wartet_bis_zur_naechsten_aktualisierung(schedule_task):
    t = schedule_task(wetter_zeitplan(latest="2026-10-10T08:00:00"))
    # Wetter aktualisiert alle 15 Minuten: nächste Prüfung um 08:15 (+1 s Puffer)
    assert t._sleep_seconds() == 10 * 60 + 1


def test_zeitplan_holt_daten_nur_wenn_faellig(schedule_task, tmp_path):
    schedule = wetter_zeitplan()
    t = schedule_task(schedule)
    action = t._determine_view_refresh(JETZT)
    action.execute(FakePlugin(), t.device_config, JETZT)
    assert schedule.get_view("w").latest_refresh_time == JETZT.isoformat()
    assert (tmp_path / "weather_Wetter_Berlin.png").exists()

    # fünf Minuten später: vorhandenes Bild, keine neuen Daten
    later = datetime(2026, 10, 10, 8, 10)
    t._determine_view_refresh(later).execute(FailingPlugin(), t.device_config, later)
    assert schedule.get_view("w").latest_refresh_time == JETZT.isoformat()


def test_zeitplan_im_hintergrund_zeigt_die_ansicht(schedule_task):
    t = schedule_task(wetter_zeitplan())
    t.start()
    try:
        t.signal_config_change()
        assert t.display_manager.started.wait(5)
    finally:
        t.stop()
    assert t.display_manager.shown == [(0, 0, 255)]
    assert t.device_config.refresh_info.plugin_instance == "Wetter Berlin"


def test_zeitplan_fehler_laesst_letztes_bild_stehen(schedule_task):
    t = schedule_task(wetter_zeitplan(), plugin=FailingPlugin())
    t.start()
    try:
        t.signal_config_change()
        for _ in range(50):
            if t.schedule_failure:
                break
            threading.Event().wait(0.1)
    finally:
        t.stop()
    assert t.display_manager.shown == []
    view_id, _, retry = t.schedule_failure
    assert view_id == "w" and retry == datetime(2026, 10, 10, 8, 10)
    # bis zum neuen Versuch wird gewartet statt sofort erneut zu probieren
    assert t._sleep_seconds() == 5 * 60 + 1
    assert t._determine_view_refresh(JETZT) is None
