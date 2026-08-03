"""Накопление результатов буста: буферизация записи и попадание в чёрный список.

Оба поведения раньше были проблемными: запись велась перечитыванием всего файла на
каждую игру (O(n²) I/O), а в чёрный список уходил любой ненулевой код возврата, из-за
чего временный сбой Steam исключал игру из всех будущих сессий навсегда.
"""

import json

from BoostiFy.core.booster import (
    PERMANENT_FAILURE_CODES,
    SUCCESS_EXIT_CODES,
    StatusListFile,
    describe_exit_code,
    reset_result_lists,
)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_entries_are_deduplicated_and_survive_flush(tmp_path):
    path = tmp_path / "black_list.json"
    writer = StatusListFile(path, flush_interval=0)  # 0 -> сбрасываем на каждой записи
    assert writer.add("570", "Dota 2", "Exit code 3") is True
    assert writer.add(570, "Dota 2 duplicate", "Exit code 3") is False  # тот же appid
    writer.flush()
    assert read(path) == [{"appid": "570", "name": "Dota 2", "status": "Exit code 3"}]


def test_writes_are_buffered_until_flush(tmp_path):
    """Между сбросами записи живут в памяти — это и убирает квадратичный I/O."""
    path = tmp_path / "white_list.json"
    writer = StatusListFile(path, flush_interval=3600)
    for index in range(50):
        writer.add(index + 1, f"Game {index}", "OK")
    assert not path.exists()  # ни одной записи на диск за 50 добавлений
    writer.flush()
    assert len(read(path)) == 50


def test_existing_file_is_loaded_and_extended(tmp_path):
    path = tmp_path / "black_list.json"
    path.write_text(json.dumps([{"appid": "10", "name": "CS", "status": "old"}]), encoding="utf-8")
    writer = StatusListFile(path, flush_interval=0)
    assert writer.known_appids() == {"10"}
    assert writer.add("10", "CS", "new") is False  # уже известен — не дублируем
    assert writer.add("20", "CS:CZ", "Exit code 3") is True
    writer.flush()
    assert [entry["appid"] for entry in read(path)] == ["10", "20"]


def test_only_game_specific_failure_is_permanent():
    """Ключевой инвариант: в чёрный список ведёт лишь отказ самой игры.

    Временные и средовые коды (-1 Steam закрыт, 101 нет ключа в реестре,
    2 не сохранились достижения) больше не хоронят игру навсегда.
    """
    assert 3 in PERMANENT_FAILURE_CODES
    for transient_code in (-1, 1, 2, 101):
        assert transient_code not in PERMANENT_FAILURE_CODES
    assert 0 in SUCCESS_EXIT_CODES and 42 in SUCCESS_EXIT_CODES
    assert not (SUCCESS_EXIT_CODES & PERMANENT_FAILURE_CODES)


def test_exit_codes_are_explained_in_plain_language():
    assert "Steam" in describe_exit_code(-1)
    assert "достижения" in describe_exit_code(2)
    assert "недоступна" in describe_exit_code(3)
    assert describe_exit_code(77) == "exit code 77"  # незнакомый код — как есть


def test_windows_unsigned_exit_code_is_understood():
    """Windows отдаёт код возврата беззнаковым DWORD.

    Воркер возвращает -1 («Steam не запущен» — самый частый сбой), а subprocess
    показывает 4294967295: без приведения подсказка промахивалась и пользователь
    видел сырое число. Значение проверено на боевом Boostify.Booster.exe.
    """
    from BoostiFy.core.booster import PERMANENT_FAILURE_CODES, signed_exit_code

    assert signed_exit_code(4294967295) == -1
    assert signed_exit_code(0xFFFFFFFD) == -3
    assert signed_exit_code(3) == 3 and signed_exit_code(0) == 0
    assert signed_exit_code("мусор") is None
    assert "Steam не ответил" in describe_exit_code(4294967295)
    # И беззнаковый вид не должен случайно совпасть с «игра недоступна».
    assert signed_exit_code(4294967295) not in PERMANENT_FAILURE_CODES


def test_batch_check_splits_long_lists_instead_of_truncating(monkeypatch):
    """Список длиннее лимита сервера режется на пачки, а не обрезается молча.

    Раньше здесь стоял срез [:500]: всё сверх лимита пропадало без следа, и игры
    выглядели «не купленными».
    """
    from BoostiFy.core.booster import SERVER_BATCH_LIMIT, SteamBooster

    booster = SteamBooster("missing.exe")
    seen = []

    def fake_request(chunk):
        seen.append(list(chunk))
        return chunk  # сервер «подтверждает» владение всем

    monkeypatch.setattr(booster, "_request_owned_batch", fake_request)
    appids = [str(index) for index in range(1, SERVER_BATCH_LIMIT * 2 + 43)]

    owned = booster.check_games_owned_batch(appids)

    assert owned == appids  # ни один AppID не потерян
    assert len(seen) == 3  # 500 + 500 + остаток
    assert all(len(chunk) <= SERVER_BATCH_LIMIT for chunk in seen)


def test_public_appid_normalizer_matches_the_boost_filter():
    """GUI обязан считать статистику по тому же набору, что уйдёт в буст."""
    from BoostiFy.core.booster import SteamBooster, normalize_appids

    raw = ["10", "0010", "bad", "0", 570, 2**32]
    assert normalize_appids(raw) == SteamBooster._normalize_appids(raw) == ["10", "570"]


def test_lookup_cache_path_is_resolved_lazily(tmp_path, monkeypatch):
    """Путь кэша каталога не должен намертво фиксироваться на импорте модуля."""
    from BoostiFy.core import app_paths, steam_lookup

    monkeypatch.setattr(app_paths, "DATA_DIR", tmp_path)
    assert steam_lookup.default_cache_file() == tmp_path / "games_upload.json"


def test_reset_clears_accumulated_lists(tmp_path):
    black = tmp_path / "black_list.json"
    white = tmp_path / "white_list.json"
    black.write_text(json.dumps([{"appid": "10", "name": "CS", "status": "err"}]), encoding="utf-8")
    white.write_text(json.dumps([{"appid": "20", "name": "CZ", "status": "OK"}]), encoding="utf-8")

    assert sorted(reset_result_lists(tmp_path)) == ["black_list.json", "white_list.json"]
    assert read(black) == [] and read(white) == []
    # Повторный сброс не сообщает о работе, которой не было.
    assert reset_result_lists(tmp_path) == []
