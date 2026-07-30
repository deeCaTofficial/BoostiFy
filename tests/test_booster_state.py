from collections import deque

import pytest

from BoostiFy.core.booster import SteamBooster


def test_session_cannot_restart_until_cleanup_finishes():
    booster = SteamBooster("missing.exe")
    session_id, stop_event = booster._begin_session()
    with pytest.raises(RuntimeError, match="Предыдущая сессия"):
        booster._begin_session()

    assert booster.stop_boost() is True
    assert stop_event.is_set()
    assert booster.is_busy is True

    booster._finish_session(session_id)
    assert booster.wait_for_stop(0.1) is True
    next_session_id, _ = booster._begin_session()
    assert next_session_id == session_id + 1
    booster._finish_session(next_session_id)


def test_appids_are_bounded_normalized_and_deduplicated():
    assert SteamBooster._normalize_appids(
        ["0010", 10, 0, -1, "bad", 2**32, 570]
    ) == ["10", "570"]


def test_failure_reason_reads_deque_tail_without_slicing_error():
    """Захваченный вывод демона — deque(maxlen), а он не поддерживает срезы.
    Прежний captured[-3:] бросал TypeError, и причина провала не попадала в black_list."""

    class FakeProc:
        returncode = 2

    proc = FakeProc()
    proc._captured_lines = deque(
        ["первая", "вторая", "FATAL ERROR: boom", "последняя"], maxlen=64
    )
    reason = SteamBooster("missing.exe")._failure_reason(proc)
    assert reason.startswith("Exit code 2")
    assert "последняя" in reason  # берём хвост из последних строк
    assert "первая" not in reason  # и только последние три
