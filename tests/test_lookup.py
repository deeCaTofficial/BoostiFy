from BoostiFy.core.steam_lookup import SteamAppLookup


def lookup_fixture():
    return SteamAppLookup(
        allow_fetch=False,
        initial_apps=[
            {"appid": 10, "name": "Counter-Strike"},
            {"appid": 20, "name": "Counter-Strike: Condition Zero"},
        ],
    )


def test_exact_lookup_accepts_punctuation_folding():
    assert lookup_fixture().find_exact_appid("Counter Strike") == 10


def test_exact_lookup_does_not_choose_ambiguous_substring():
    assert lookup_fixture().find_exact_appid("Counter") is None
    assert len(lookup_fixture().find_similar("Counter")) == 2


def test_store_search_matches_only_the_exact_title(monkeypatch):
    """Локальный каталог не обновляется, поэтому имя спрашиваем у магазина.

    Берём лишь полное совпадение: на «Half-Life» магазин первым отдаёт
    «Half-Life 2», и частичное совпадение увело бы не на ту игру.
    """
    import json
    import urllib.request

    from BoostiFy.core import steam_lookup

    payload = {"items": [
        {"id": 220, "name": "Half-Life 2", "type": "app"},
        {"id": 70, "name": "Half-Life", "type": "app"},
    ]}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Response())
    assert steam_lookup.search_store_exact("Half-Life") == (70, "Half-Life")
    # Пунктуация складывается так же, как в локальном каталоге.
    assert steam_lookup.search_store_exact("half life") == (70, "Half-Life")
    assert steam_lookup.search_store_exact("Portal") is None


def test_store_search_survives_network_failure(monkeypatch):
    import urllib.error
    import urllib.request

    from BoostiFy.core import steam_lookup

    def boom(*args, **kwargs):
        raise urllib.error.URLError("нет сети")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert steam_lookup.search_store_exact("Half-Life") is None


def _cached_lookup(tmp_path, age_seconds):
    import json
    import os
    import time

    cache = tmp_path / "games_upload.json"
    cache.write_text(json.dumps([{"appid": 10, "name": "Counter-Strike"}]), encoding="utf-8")
    stamp = time.time() - age_seconds
    os.utime(cache, (stamp, stamp))
    return SteamAppLookup(allow_fetch=False, cache_file=cache)


def test_stale_catalog_is_refreshed_when_asked(tmp_path, monkeypatch):
    """Каталог, скачанный однажды, жил вечно — «Добавить все игры» не видела новинок."""
    from BoostiFy.core.steam_lookup import CATALOG_MAX_AGE_SEC

    lookup = _cached_lookup(tmp_path, CATALOG_MAX_AGE_SEC + 60)
    fresh = [{"appid": 10, "name": "Counter-Strike", "status": "Готово"},
             {"appid": 4212480, "name": "Новая игра", "status": "Готово"}]
    monkeypatch.setattr(lookup, "fetch_applist", lambda: fresh)
    assert lookup.ensure_loaded(max_age=CATALOG_MAX_AGE_SEC)
    assert lookup.get_name(4212480) == "Новая игра"


def test_fresh_catalog_is_not_downloaded_again(tmp_path, monkeypatch):
    lookup = _cached_lookup(tmp_path, 60)
    calls = []
    monkeypatch.setattr(lookup, "fetch_applist", lambda: calls.append(1) or [])
    assert lookup.ensure_loaded(max_age=3600)
    assert calls == []


def test_failed_refresh_keeps_the_old_catalog(tmp_path, monkeypatch):
    lookup = _cached_lookup(tmp_path, 10 ** 7)
    monkeypatch.setattr(lookup, "fetch_applist", list)
    assert lookup.ensure_loaded(max_age=60)
    assert lookup.find_exact_appid("Counter-Strike") == 10
