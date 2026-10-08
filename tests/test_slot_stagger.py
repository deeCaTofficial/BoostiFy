import tempfile
import threading
import time
from unittest import mock

from BoostiFy.core import booster
from BoostiFy.core.booster import SLOT_START_STAGGER_SEC, SteamBooster


class _FakeProc:
    returncode = 0
    stdout = None

    def wait(self, timeout=None):
        return 0

    def poll(self):
        return 0

    def kill(self):
        pass

    def terminate(self):
        pass


def _run_batch(slots, hold_seconds, watch_seconds, stagger=None):
    """Запускает пачку с подменённым процессом и возвращает моменты запусков."""
    launches = []
    lock = threading.Lock()
    boost = SteamBooster.__new__(SteamBooster)
    SteamBooster.__init__(boost)

    def fake_run(appid, **kwargs):
        with lock:
            launches.append(time.time())
        return _FakeProc()

    boost._run_steambooster = fake_run
    # Слот занят, пока игра «идёт»: без этого один слот успевает разобрать всю
    # очередь до того, как проснутся остальные, и разгона не видно.
    boost._wait_process = lambda proc, event: event.wait(hold_seconds)
    boost._finish_task = lambda *args, **kwargs: None

    step = SLOT_START_STAGGER_SEC if stagger is None else stagger
    with (
        mock.patch.object(booster, "build_name_map", dict),
        mock.patch.object(booster, "get_upload_dir", lambda: tempfile.mkdtemp()),
        mock.patch.object(booster, "SLOT_START_STAGGER_SEC", step),
    ):
        start = time.time()
        boost.start_boost_sliding(
            [str(1000 + i) for i in range(slots)],
            num_slots=slots,
            duration_sec=30,
            launch_cd_range=(0, 0),
            finish_cd_range=(0, 0),
            slot_cd_range=(0, 0),
        )
        time.sleep(watch_seconds)
        stop_started = time.time()
        boost.stop_boost()
        stop_took = time.time() - stop_started
    return sorted(moment - start for moment in launches), stop_took


def test_slots_do_not_all_start_at_once():
    """Steam получал всю пачку разом, и steamwebhelper переставал отвечать.

    Потоки слотов создаются подряд без пауз, а «КД начала» все отсчитывают от
    одного момента — при 60 слотах это 60 подключений в одном коротком окне.
    """
    offsets, _ = _run_batch(slots=6, hold_seconds=25, watch_seconds=6, stagger=1.0)
    assert len(offsets) >= 5
    gaps = [offsets[i + 1] - offsets[i] for i in range(len(offsets) - 1)]
    assert all(0.7 <= gap <= 1.4 for gap in gaps), gaps


def test_stagger_scales_with_slot_number():
    """Каждый следующий слот ждёт на шаг дольше предыдущего."""
    offsets, _ = _run_batch(slots=4, hold_seconds=25, watch_seconds=5, stagger=1.0)
    assert offsets[0] < 0.5
    for index, offset in enumerate(offsets):
        assert abs(offset - index) < 0.5, offsets


def test_stop_stays_instant_during_the_ramp():
    """Разгон ждёт на stop_event, а не на sleep: остановка не должна тормозить."""
    _, stop_took = _run_batch(slots=8, hold_seconds=25, watch_seconds=2, stagger=5.0)
    assert stop_took < 3.0, stop_took
