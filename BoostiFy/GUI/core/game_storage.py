import json
import os
import threading
import uuid
from pathlib import Path

from BoostiFy.core.app_paths import DATA_DIR, migrate_legacy_data, replace_with_retry

DEFAULT_CONFIG = {
    "concurrent_value": 60,
    "duration_value": 30,
    "unlock_achievements": False,
    "fast_paste_enabled": True,
    "time_mode": 0,
    "loop_boost": False,
    "table_visible_rows": 15,
    "auto_clean_table": False,
    "launch_cd_from": 1,
    "launch_cd_to": 6,
    "finish_cd_from": 1,
    "finish_cd_to": 6,
    "slot_cd_from": 5,
    "slot_cd_to": 10,
}

# Минимальный разрыв между «от» и «до» каждого КД: верхняя граница всегда
# не меньше нижней + этого запаса, чтобы диапазон рандома не схлопывался в точку.
MIN_CD_SPREAD = 5

# Границы каждого КД: (нижняя_min, нижняя_max), (верхняя_min, верхняя_max).
# Пол верхней границы = пол нижней + MIN_CD_SPREAD, иначе часть объявленного
# диапазона недостижима: при поле «до» = 2 и разрыве 5 значения 2..5 выставить
# нельзя было в принципе, и кнопка «-» ниже 6 просто переставала реагировать.
CD_BOUNDS = {
    "launch": ((1, 59), (1 + MIN_CD_SPREAD, 120)),
    "finish": ((1, 59), (1 + MIN_CD_SPREAD, 120)),
    "slot": ((5, 300), (5 + MIN_CD_SPREAD, 600)),
}

# Сколько строк показывать в таблице. Пол подняли с 5 до 10: на меньших значениях
# строки разъезжались в полосы высотой под 73 px, и таблица переставала читаться
# как список. Границы живут здесь же, что и CD_BOUNDS, — ими пользуются и
# normalize_config, и кнопки «+»/«-» на вкладке настроек.
TABLE_ROWS_BOUNDS = (10, 20)

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
        with open(path, encoding="utf-8-sig") as stream:
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
            replace_with_retry(temporary, destination)
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
        "concurrent_value": _bounded_int(source.get("concurrent_value"), 60, 1, 60),
        "duration_value": _bounded_int(source.get("duration_value"), 30, 30, 604800),
        "unlock_achievements": _as_bool(source.get("unlock_achievements"), False),
        "fast_paste_enabled": _as_bool(source.get("fast_paste_enabled"), True),
        "time_mode": _bounded_int(source.get("time_mode"), 0, 0, 1),
        "loop_boost": _as_bool(source.get("loop_boost"), False),
        "table_visible_rows": _bounded_int(
            source.get("table_visible_rows"),
            DEFAULT_CONFIG["table_visible_rows"],
            *TABLE_ROWS_BOUNDS,
        ),
        "auto_clean_table": _as_bool(source.get("auto_clean_table"), False),
        **{
            f"{pair}_cd_{edge}": _bounded_int(
                source.get(f"{pair}_cd_{edge}"), DEFAULT_CONFIG[f"{pair}_cd_{edge}"], low, high
            )
            for pair, bounds in CD_BOUNDS.items()
            for edge, (low, high) in zip(("from", "to"), bounds, strict=True)
        },
    }
    # Держим верхнюю границу не ближе MIN_CD_SPREAD к нижней (from_max + spread не
    # превышает потолок «до» ни у одного КД, поэтому переполнения границы не будет).
    normalized["launch_cd_to"] = max(normalized["launch_cd_from"] + MIN_CD_SPREAD, normalized["launch_cd_to"])
    normalized["finish_cd_to"] = max(normalized["finish_cd_from"] + MIN_CD_SPREAD, normalized["finish_cd_to"])
    normalized["slot_cd_to"] = max(normalized["slot_cd_from"] + MIN_CD_SPREAD, normalized["slot_cd_to"])
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
