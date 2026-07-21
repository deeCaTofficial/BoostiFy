import json

from BoostiFy.GUI.core import game_storage
from BoostiFy.GUI.core.statistics_storage import (
    classify_game_statuses,
    finish_statistics_session,
    load_statistics,
    reset_statistics,
    start_statistics_session,
)


def test_statistics_session_is_accumulated_and_reset_safely(tmp_path):
    game_storage.configure_storage(tmp_path)
    reset_statistics()

    session_id = start_statistics_session(4, now=100)
    assert finish_statistics_session(
        session_id,
        successful_games=2,
        failed_games=1,
        skipped_games=1,
        now=160,
    )

    stats = load_statistics()
    assert stats["total_sessions"] == 1
    assert stats["completed_sessions"] == 1
    assert stats["successful_games"] == 2
    assert stats["failed_games"] == 1
    assert stats["skipped_games"] == 1
    assert stats["total_runtime_seconds"] == 60
    assert stats["last_session"]["games_total"] == 4
    assert stats["active_session"] is None

    reset_statistics()
    reset = load_statistics()
    assert reset["total_sessions"] == 0
    assert reset["last_session"] is None


def test_new_session_recovers_unfinished_previous_session(tmp_path):
    game_storage.configure_storage(tmp_path)
    first_id = start_statistics_session(3, now=100)
    second_id = start_statistics_session(2, now=130)

    stats = load_statistics()
    assert first_id != second_id
    assert stats["total_sessions"] == 1
    assert stats["stopped_sessions"] == 1
    assert stats["interrupted_sessions"] == 1
    assert stats["last_session"]["duration_seconds"] == 30
    assert stats["active_session"]["id"] == second_id


def test_statistics_normalizes_corrupt_values_and_statuses(tmp_path):
    game_storage.configure_storage(tmp_path)
    (tmp_path / "statistics.json").write_text(
        json.dumps(
            {
                "total_sessions": -20,
                "successful_games": "7",
                "failed_games": "bad",
                "recent_sessions": "not-a-list",
                "active_session": {"id": "", "started_at": -1},
            }
        ),
        encoding="utf-8",
    )
    stats = load_statistics()
    assert stats["total_sessions"] == 0
    assert stats["successful_games"] == 7
    assert stats["failed_games"] == 0
    assert stats["recent_sessions"] == []
    assert stats["active_session"] is None

    counts = classify_game_statuses(
        [
            {"status": "Готово"},
            {"status": "Ошибка: Steam"},
            {"status": "Не выполнено"},
            {"status": "Пропущено: чёрный список"},
            {"status": "Ожидание"},
        ]
    )
    assert counts == {"successful": 1, "failed": 2, "skipped": 1, "other": 1}
