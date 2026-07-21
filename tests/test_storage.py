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
    assert config["concurrent_value"] == 60
    assert config["duration_value"] == 900
    assert config["unlock_achievements"] is False
    assert config["launch_cd_to"] == 50


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


def test_invalid_json_falls_back_without_destroying_file(tmp_path):
    game_storage.configure_storage(tmp_path)
    config_path = tmp_path / "config.json"
    config_path.write_text("{broken", encoding="utf-8")
    assert game_storage.load_config() == game_storage.DEFAULT_CONFIG
    assert config_path.read_text(encoding="utf-8") == "{broken"
