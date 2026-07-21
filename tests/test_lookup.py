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
