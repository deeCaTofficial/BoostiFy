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


def test_request_on_a_closed_server_reports_cleanly(monkeypatch):
    """Сервер могли закрыть между проверкой и записью в stdin.

    Раньше self._server_proc.stdin падало с AttributeError на None и выдавалось
    пользователю за «Ошибку проверки Steam», хотя это гонка внутри приложения.
    """
    booster = SteamBooster("missing.exe")
    monkeypatch.setattr(booster, "_ensure_server_running", lambda: True)
    booster._server_proc = None  # другой поток успел выполнить shutdown_server()

    assert booster._active_server() is None
    for call in (lambda: booster.check_game_owned(570),
                 lambda: booster.check_games_owned_batch(["570"])):
        with pytest.raises(RuntimeError, match="остановлена"):
            call()


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
    # Причина теперь начинается с человеческого описания кода, а не с «Exit code N».
    assert "не удалось сохранить достижения (код 2)" in reason
    assert "последняя" in reason  # берём хвост из последних строк
    assert "первая" not in reason  # и только последние три
