import os

import pytest

from BoostiFy.GUI.core import game_storage


def test_config_is_clamped_and_wrong_types_fall_back():
    config = game_storage.normalize_config(
        {
            "concurrent_value": 500,
            "duration_value": "bad",
            "unlock_achievements": "yes",
            "launch_cd_from": 50,
            "launch_cd_to": 2,
        }
    )
    assert config["concurrent_value"] == 60  # 500 зажато до максимума (60)
    assert config["duration_value"] == 30  # "bad" -> дефолт (30)
    assert config["unlock_achievements"] is False
    # Верхняя граница держит минимальный разрыв: 50 + MIN_CD_SPREAD (5).
    assert config["launch_cd_to"] == 55


def test_games_are_validated_and_deduplicated(tmp_path):
    game_storage.configure_storage(tmp_path)
    game_storage.save_games(
        [
            {"appid": "10", "name": "Counter-Strike", "status": "Готово"},
            {"appid": "0010", "name": "Duplicate", "status": "Ошибка"},
            {"appid": "-1", "name": "Bad", "status": "Bad"},
            {"broken": True},
        ]
    )
    assert game_storage.load_games() == [
        {"appid": "10", "name": "Counter-Strike", "status": "Готово"}
    ]


def test_cooldown_bounds_leave_no_unreachable_values():
    """Пол верхней границы обязан быть достижим при минимальном разрыве.

    Пока пол «до» был 2 при поле «от» 1 и разрыве 5, значения 2..5 выставить было
    нельзя в принципе — кнопка «-» ниже 6 просто переставала реагировать.
    """
    for pair, ((low_from, _), (low_to, _)) in game_storage.CD_BOUNDS.items():
        assert low_to == low_from + game_storage.MIN_CD_SPREAD, pair
        # Пол диапазона переживает нормализацию без сдвига.
        config = game_storage.normalize_config(
            {f"{pair}_cd_from": low_from, f"{pair}_cd_to": low_to}
        )
        assert config[f"{pair}_cd_from"] == low_from
        assert config[f"{pair}_cd_to"] == low_to


def test_replace_retries_transient_windows_lock(tmp_path, monkeypatch):
    """Подмена файла на Windows падает с PermissionError, если его кто-то открыл.

    Причина транзиентная (антивирус, индексатор, параллельное чтение), но без
    повторов запись просто терялась: под нагрузкой проваливалось 479 сохранений
    из 480, и правки таблицы молча не доходили до диска.
    """
    from BoostiFy.core import app_paths

    source = tmp_path / "src.tmp"
    destination = tmp_path / "dst.json"
    source.write_text("[]", encoding="utf-8")
    calls = []
    real_replace = os.replace

    def flaky_replace(src, dst):
        calls.append(1)
        if len(calls) < 3:  # первые две попытки — «файл занят»
            raise PermissionError(5, "Access is denied")
        real_replace(src, dst)

    monkeypatch.setattr(app_paths.os, "replace", flaky_replace)
    app_paths.replace_with_retry(source, destination, delay=0)
    assert destination.exists() and len(calls) == 3

    # Если файл занят навсегда — ошибка не проглатывается.
    monkeypatch.setattr(
        app_paths.os, "replace",
        lambda *_: (_ for _ in ()).throw(PermissionError(5, "Access is denied")),
    )
    with pytest.raises(PermissionError):
        app_paths.replace_with_retry(source, destination, attempts=2, delay=0)


def test_defaults_survive_normalization():
    assert game_storage.normalize_config(game_storage.DEFAULT_CONFIG) == game_storage.DEFAULT_CONFIG


def test_invalid_json_falls_back_without_destroying_file(tmp_path):
    game_storage.configure_storage(tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text("{broken", encoding="utf-8")
    assert game_storage.load_config() == game_storage.DEFAULT_CONFIG
    assert config_path.read_text(encoding="utf-8") == "{broken"
