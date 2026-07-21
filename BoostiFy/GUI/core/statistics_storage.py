import time
import uuid
from copy import deepcopy
from pathlib import Path

from BoostiFy.GUI.core import game_storage


MAX_RECENT_SESSIONS = 8
DEFAULT_STATISTICS = {
    "version": 1,
    "total_sessions": 0,
    "completed_sessions": 0,
    "stopped_sessions": 0,
    "interrupted_sessions": 0,
    "successful_games": 0,
    "failed_games": 0,
    "skipped_games": 0,
    "total_runtime_seconds": 0,
    "last_session": None,
    "recent_sessions": [],
    "active_session": None,
}


def classify_game_statuses(games):
    counts = {"successful": 0, "failed": 0, "skipped": 0, "other": 0}
    for game in games if isinstance(games, (list, tuple)) else []:
        status = str(game.get("status", "") if isinstance(game, dict) else "").strip().lower()
        if status.startswith("готово"):
            counts["successful"] += 1
        elif status.startswith("ошибка") or status.startswith("не выполнено"):
            counts["failed"] += 1
        elif status.startswith("пропущено"):
            counts["skipped"] += 1
        else:
            counts["other"] += 1
    return counts


def _statistics_path() -> Path:
    # Путь вычисляется динамически, чтобы configure_storage() оставался герметичным в тестах.
    return Path(game_storage.UPLOAD_DIR) / "statistics.json"


def _safe_int(value, minimum=0, maximum=10**12):
    if isinstance(value, bool):
        return minimum
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        return minimum
    return max(minimum, min(maximum, value))


def _safe_timestamp(value):
    try:
        value = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return max(0.0, min(time.time() + 86400, value))


def _normalize_session(value, *, active=False):
    if not isinstance(value, dict):
        return None
    session_id = str(value.get("id") or "").strip()[:64]
    started_at = _safe_timestamp(value.get("started_at"))
    if not session_id or not started_at:
        return None
    session = {
        "id": session_id,
        "started_at": started_at,
        "games_total": _safe_int(value.get("games_total"), maximum=1_000_000),
    }
    if active:
        return session
    finished_at = max(started_at, _safe_timestamp(value.get("finished_at")))
    session.update(
        {
            "finished_at": finished_at,
            "duration_seconds": _safe_int(value.get("duration_seconds"), maximum=10**9),
            "successful_games": _safe_int(value.get("successful_games"), maximum=1_000_000),
            "failed_games": _safe_int(value.get("failed_games"), maximum=1_000_000),
            "skipped_games": _safe_int(value.get("skipped_games"), maximum=1_000_000),
            "stopped": bool(value.get("stopped", False)),
            "interrupted": bool(value.get("interrupted", False)),
        }
    )
    return session


def normalize_statistics(value):
    source = value if isinstance(value, dict) else {}
    total_sessions = _safe_int(source.get("total_sessions"))
    completed_sessions = min(total_sessions, _safe_int(source.get("completed_sessions")))
    stopped_sessions = min(
        total_sessions - completed_sessions,
        _safe_int(source.get("stopped_sessions")),
    )
    interrupted_sessions = min(stopped_sessions, _safe_int(source.get("interrupted_sessions")))
    recent = []
    for item in source.get("recent_sessions", []) if isinstance(source.get("recent_sessions"), list) else []:
        session = _normalize_session(item)
        if session is not None:
            recent.append(session)
        if len(recent) >= MAX_RECENT_SESSIONS:
            break
    last_session = _normalize_session(source.get("last_session"))
    if last_session is None and recent:
        last_session = deepcopy(recent[0])
    return {
        "version": 1,
        "total_sessions": total_sessions,
        "completed_sessions": completed_sessions,
        "stopped_sessions": stopped_sessions,
        "interrupted_sessions": interrupted_sessions,
        "successful_games": _safe_int(source.get("successful_games")),
        "failed_games": _safe_int(source.get("failed_games")),
        "skipped_games": _safe_int(source.get("skipped_games")),
        "total_runtime_seconds": _safe_int(source.get("total_runtime_seconds"), maximum=10**15),
        "last_session": last_session,
        "recent_sessions": recent,
        "active_session": _normalize_session(source.get("active_session"), active=True),
    }


def load_statistics():
    value = game_storage._load_json(_statistics_path(), deepcopy(DEFAULT_STATISTICS))
    return normalize_statistics(value)


def save_statistics(value):
    normalized = normalize_statistics(value)
    game_storage._atomic_write_json(_statistics_path(), normalized)
    return normalized


def start_statistics_session(games_total, now=None):
    stats = load_statistics()
    # Незакрытый сеанс означает аварийное завершение прошлого запуска.
    if stats["active_session"] is not None:
        _finish_active_session(stats, stopped=True, interrupted=True, now=now)
    session_id = uuid.uuid4().hex
    stats["active_session"] = {
        "id": session_id,
        "started_at": float(time.time() if now is None else now),
        "games_total": _safe_int(games_total, maximum=1_000_000),
    }
    save_statistics(stats)
    return session_id


def discard_statistics_session(session_id):
    stats = load_statistics()
    active = stats.get("active_session")
    if active is None or active.get("id") != str(session_id or ""):
        return False
    stats["active_session"] = None
    save_statistics(stats)
    return True


def _finish_active_session(
    stats,
    successful_games=0,
    failed_games=0,
    skipped_games=0,
    stopped=False,
    interrupted=False,
    now=None,
):
    active = stats.get("active_session")
    if active is None:
        return None
    finished_at = max(float(active["started_at"]), float(time.time() if now is None else now))
    total = active["games_total"]
    successful = min(total, _safe_int(successful_games, maximum=1_000_000))
    failed = min(total - successful, _safe_int(failed_games, maximum=1_000_000))
    skipped = min(total - successful - failed, _safe_int(skipped_games, maximum=1_000_000))
    session = {
        **active,
        "finished_at": finished_at,
        "duration_seconds": max(0, int(finished_at - float(active["started_at"]))),
        "successful_games": successful,
        "failed_games": failed,
        "skipped_games": skipped,
        "stopped": bool(stopped),
        "interrupted": bool(interrupted),
    }
    stats["total_sessions"] += 1
    stats["completed_sessions"] += int(not stopped and not interrupted)
    stats["stopped_sessions"] += int(bool(stopped))
    stats["interrupted_sessions"] += int(bool(interrupted))
    stats["successful_games"] += successful
    stats["failed_games"] += failed
    stats["skipped_games"] += skipped
    stats["total_runtime_seconds"] += session["duration_seconds"]
    stats["last_session"] = session
    stats["recent_sessions"] = [session, *stats["recent_sessions"]][:MAX_RECENT_SESSIONS]
    stats["active_session"] = None
    return session


def finish_statistics_session(
    session_id,
    *,
    successful_games=0,
    failed_games=0,
    skipped_games=0,
    stopped=False,
    interrupted=False,
    now=None,
):
    stats = load_statistics()
    active = stats.get("active_session")
    if active is None or active.get("id") != str(session_id or ""):
        return False
    _finish_active_session(
        stats,
        successful_games=successful_games,
        failed_games=failed_games,
        skipped_games=skipped_games,
        stopped=stopped,
        interrupted=interrupted,
        now=now,
    )
    save_statistics(stats)
    return True


def reset_statistics():
    current = load_statistics()
    reset = deepcopy(DEFAULT_STATISTICS)
    # Активную работу нельзя потерять даже при программном вызове сброса.
    reset["active_session"] = current.get("active_session")
    return save_statistics(reset)
