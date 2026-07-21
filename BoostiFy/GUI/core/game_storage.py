import json
import os
import threading
import uuid
from pathlib import Path

from BoostiFy.core.app_paths import DATA_DIR, migrate_legacy_data


DEFAULT_CONFIG = {
    "concurrent_value": 15,
    "duration_value": 900,
    "unlock_achievements": False,
    "fast_paste_enabled": False,
    "time_mode": 0,
    "loop_boost": False,
    "table_visible_rows": 15,
    "auto_clean_table": False,
    "launch_cd_from": 5,
    "launch_cd_to": 35,
    "finish_cd_from": 5,
    "finish_cd_to": 35,
    "slot_cd_from": 60,
    "slot_cd_to": 90,
}

UPLOAD_DIR = str(DATA_DIR)
USER_GAMES_FILE = str(DATA_DIR / "user_games.json")
CONFIG_FILE = str(DATA_DIR / "config.json")
_write_lock = threading.RLock()


def configure_storage(directory) -> None:
    """Redirect storage, primarily for tests and portable deployments."""
    global UPLOAD_DIR, USER_GAMES_FILE, CONFIG_FILE
    base = Path(directory).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR = str(base)
    USER_GAMES_FILE = str(base / "user_games.json")
    CONFIG_FILE = str(base / "config.json")


def ensure_storage_ready(migrate: bool = True) -> None:
    Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    if migrate:
        migrate_legacy_data(Path(UPLOAD_DIR))
    ensure_default_config()


def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8-sig") as stream:
            return json.load(stream)
    except (OSError, json.JSONDecodeError, UnicodeError) as error:
        if os.path.exists(path):
            print(f"Не удалось прочитать JSON {path}: {error}")
        return default


def _atomic_write_json(path, data):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f"{destination.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )
    with _write_lock:
        try:
            with temporary.open("w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _as_bool(value, default):
    return value if isinstance(value, bool) else default


def _bounded_int(value, default, minimum, maximum):
    if isinstance(value, bool):
        return default
    try:
        value = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, min(maximum, value))


def normalize_config(config):
    source = config if isinstance(config, dict) else {}
    normalized = {
        "concurrent_value": _bounded_int(source.get("concurrent_value"), 15, 1, 60),
        "duration_value": _bounded_int(source.get("duration_value"), 900, 30, 604800),
        "unlock_achievements": _as_bool(source.get("unlock_achievements"), False),
        "fast_paste_enabled": _as_bool(source.get("fast_paste_enabled"), False),
        "time_mode": _bounded_int(source.get("time_mode"), 0, 0, 1),
        "loop_boost": _as_bool(source.get("loop_boost"), False),
        "table_visible_rows": _bounded_int(source.get("table_visible_rows"), 15, 5, 50),
        "auto_clean_table": _as_bool(source.get("auto_clean_table"), False),
        "launch_cd_from": _bounded_int(source.get("launch_cd_from"), 5, 1, 59),
        "launch_cd_to": _bounded_int(source.get("launch_cd_to"), 35, 2, 120),
        "finish_cd_from": _bounded_int(source.get("finish_cd_from"), 5, 1, 59),
        "finish_cd_to": _bounded_int(source.get("finish_cd_to"), 35, 2, 120),
        "slot_cd_from": _bounded_int(source.get("slot_cd_from"), 60, 5, 300),
        "slot_cd_to": _bounded_int(source.get("slot_cd_to"), 90, 10, 600),
    }
    normalized["launch_cd_to"] = max(normalized["launch_cd_from"], normalized["launch_cd_to"])
    normalized["finish_cd_to"] = max(normalized["finish_cd_from"], normalized["finish_cd_to"])
    normalized["slot_cd_to"] = max(normalized["slot_cd_from"], normalized["slot_cd_to"])
    return normalized


def _normalize_game(game):
    if not isinstance(game, dict):
        return None
    raw_appid = str(game.get("appid", "")).strip()
    if not raw_appid.isdigit():
        return None
    appid = int(raw_appid)
    if appid <= 0 or appid > 0xFFFFFFFF:
        return None
    name = str(game.get("name") or appid).strip()[:300]
    status = str(game.get("status") or "Ожидание").strip()[:500]
    return {"appid": str(appid), "name": name or str(appid), "status": status or "Ожидание"}


def load_games():
    games = _load_json(USER_GAMES_FILE, [])
    if not isinstance(games, list):
        return []
    normalized = []
    seen = set()
    for game in games:
        item = _normalize_game(game)
        if item and item["appid"] not in seen:
            normalized.append(item)
            seen.add(item["appid"])
    return normalized


def save_games(games):
    normalized = []
    seen = set()
    for game in games if isinstance(games, (list, tuple)) else []:
        item = _normalize_game(game)
        if item and item["appid"] not in seen:
            normalized.append(item)
            seen.add(item["appid"])
    _atomic_write_json(USER_GAMES_FILE, normalized)


def load_config():
    return normalize_config(_load_json(CONFIG_FILE, DEFAULT_CONFIG.copy()))


def save_config(config):
    _atomic_write_json(CONFIG_FILE, normalize_config(config))


def ensure_default_config():
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
