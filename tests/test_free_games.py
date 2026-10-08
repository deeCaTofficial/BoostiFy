import json
import urllib.error
import urllib.request

import pytest

from BoostiFy.core import app_paths, free_games


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    """Каталог данных на время теста: иначе состояние ляжет в настоящий профиль."""
    monkeypatch.setattr(app_paths, "DATA_DIR", tmp_path)
    return tmp_path


def offer(appid, package_id, kind="game", parent="", name=None):
    return free_games.FreeOffer(
        appid=str(appid),
        name=name or f"Игра {appid}",
        package_id=package_id,
        kind=kind,
        parent_appid=str(parent),
        parent_name=f"Родитель {parent}" if parent else "",
    )


# ------------------------------- разбор ответов -------------------------------

def test_search_url_includes_paid_with_full_discount():
    url = free_games.search_url()
    assert "maxprice=free" in url and "specials=1" in url
    # Без category1: раздают в основном дополнения, а этот фильтр их отсекает.
    assert "category1" not in url


def test_search_url_can_narrow_to_games_only():
    assert "category1=998" in free_games.search_url(include_extras=False)


def test_parse_search_results_reads_rows_and_drops_duplicates():
    html = (
        '<a data-ds-appid="10"><span class="title">Alpha</span></a>'
        '<a data-ds-appid="20"><span class="title">Beta</span></a>'
        '<a data-ds-appid="10"><span class="title">Alpha</span></a>'
    )
    assert free_games.parse_search_results({"results_html": html}) == [
        ("10", "Alpha"), ("20", "Beta"),
    ]


@pytest.mark.parametrize("payload", [{}, {"results_html": None}, [], "не json", None])
def test_parse_search_results_survives_junk(payload):
    assert free_games.parse_search_results(payload) == []


def test_find_free_package_picks_promo_not_the_paid_twin():
    """У одного продукта в списке лежат оба пакета — даровой и платный."""
    payload = {"7": {"success": True, "data": {"package_groups": [{"subs": [
        {"packageid": 111, "is_free_license": False, "price_in_cents_with_discount": 999},
        {"packageid": 222, "is_free_license": True, "price_in_cents_with_discount": 0},
    ]}]}}}
    assert free_games.find_free_package(payload, "7") == 222


def test_find_free_package_ignores_zero_price_without_free_license():
    payload = {"7": {"success": True, "data": {"package_groups": [{"subs": [
        {"packageid": 111, "is_free_license": False, "price_in_cents_with_discount": 0},
    ]}]}}}
    assert free_games.find_free_package(payload, "7") is None


@pytest.mark.parametrize("payload", [
    {}, {"7": {"success": False}}, {"7": {"success": True, "data": None}},
    {"7": {"success": True, "data": {"package_groups": None}}},
    {"7": {"success": True, "data": {"package_groups": [{"subs": [{"packageid": "нет"}]}]}}},
])
def test_find_free_package_survives_junk(payload):
    assert free_games.find_free_package(payload, "7") is None


def test_describe_app_reads_kind_and_parent():
    payload = {"5": {"success": True, "data": {
        "type": "music", "name": "Саундтрек",
        "fullgame": {"appid": "99", "name": "Базовая игра"},
    }}}
    info = free_games.describe_app(payload, "5")
    assert info == {
        "kind": "music", "parent_appid": "99",
        "parent_name": "Базовая игра", "name": "Саундтрек",
    }


def test_describe_app_defaults_to_game_without_parent():
    payload = {"5": {"success": True, "data": {"type": "game", "name": "Игра"}}}
    info = free_games.describe_app(payload, "5")
    assert info["kind"] == "game" and info["parent_appid"] == ""


def test_parse_free_dlc_keeps_only_free_items():
    payload = {"dlc": [
        {"id": 1, "name": "Даровое"},                                   # блока цены нет
        {"id": 2, "name": "Платное", "price_overview": {"final": 3999}},
        {"id": 3, "name": "Скидка 100%", "price_overview": {"final": 0}},
        {"id": "мусор", "name": "Не число"},
        {"сломано": True},
    ]}
    assert free_games.parse_free_dlc(payload) == [("1", "Даровое"), ("3", "Скидка 100%")]


@pytest.mark.parametrize("payload", [{}, {"dlc": None}, {"dlc": "строка"}, "не json", None])
def test_parse_free_dlc_survives_junk(payload):
    assert free_games.parse_free_dlc(payload) == []


# ------------------------- правило про базовую игру -------------------------

def test_plain_game_offer_needs_no_parent():
    steps, skipped = free_games.plan_claims([offer(10, 100)], owned_appids=[])
    assert skipped == []
    assert [(s.appid, s.reason) for s in steps] == [("10", "offer")]


def test_dlc_is_skipped_when_base_game_cannot_be_had_for_free():
    """Главное правило: без базовой игры лицензия на дополнение бесполезна."""
    steps, skipped = free_games.plan_claims(
        [offer(11, 101, kind="dlc", parent="99")],
        owned_appids=[],
        package_lookup=lambda appid: None,   # базовая игра платная
    )
    assert steps == []
    assert len(skipped) == 1 and "базовой игры" in skipped[0][1]


def test_dlc_passes_when_base_game_is_already_owned():
    steps, skipped = free_games.plan_claims(
        [offer(11, 101, kind="dlc", parent="99")],
        owned_appids=["99"],
        package_lookup=lambda appid: pytest.fail("владеем — искать пакет незачем"),
    )
    assert skipped == []
    assert [(s.appid, s.reason) for s in steps] == [("11", "offer")]


def test_free_base_game_is_claimed_before_its_dlc():
    """Порядок важен: сначала игра, потом дополнение к ней."""
    steps, skipped = free_games.plan_claims(
        [offer(11, 101, kind="music", parent="99")],
        owned_appids=[],
        package_lookup=lambda appid: 900 if appid == "99" else None,
    )
    assert skipped == []
    assert [(s.appid, s.reason) for s in steps] == [("99", "parent"), ("11", "offer")]


def test_shared_base_game_is_claimed_once_for_several_dlc():
    steps, _ = free_games.plan_claims(
        [offer(11, 101, kind="dlc", parent="99"), offer(12, 102, kind="dlc", parent="99")],
        owned_appids=[],
        package_lookup=lambda appid: 900,
    )
    assert [(s.appid, s.reason) for s in steps] == [
        ("99", "parent"), ("11", "offer"), ("12", "offer"),
    ]


def test_already_owned_and_already_claimed_are_dropped():
    offers = [offer(10, 100), offer(20, 200), offer(30, 300)]
    steps, _ = free_games.plan_claims(offers, owned_appids=["20"], claimed_ids=[300])
    assert [s.appid for s in steps] == ["10"]


def test_claim_url_points_at_the_steam_client():
    step = free_games.ClaimStep(appid="10", name="Игра", package_id=777)
    assert step.claim_url == "steam://subscriptioninstall/777"


# ---------------------- дополнения к играм из библиотеки ----------------------

def test_scan_collects_free_dlc_of_owned_games():
    library = {"1": [("11", "DLC A")], "2": [], "3": [("33", "DLC B"), ("34", "DLC C")]}
    found, scanned = free_games.scan_owned_for_free_dlc(
        ["1", "2", "3"], delay=0, dlc_lookup=lambda appid: library[appid],
    )
    assert scanned == 3
    assert found == [("11", "DLC A", "1"), ("33", "DLC B", "3"), ("34", "DLC C", "3")]


def test_scan_stops_at_the_limit():
    """Библиотека бывает в тысячи позиций: один проход обязан быть коротким."""
    seen = []

    def lookup(appid):
        seen.append(appid)
        return []

    _, scanned = free_games.scan_owned_for_free_dlc(
        [str(i) for i in range(100)], limit=5, delay=0, dlc_lookup=lookup,
    )
    assert scanned == 5 and len(seen) == 5


def test_resolve_dlc_offers_keeps_only_those_with_a_free_package():
    candidates = [("11", "Есть пакет", "1"), ("12", "Нет пакета", "1"), ("13", "Уже брали", "1")]
    packages = {"11": 901, "12": None, "13": 903}
    offers = free_games.resolve_dlc_offers(
        candidates, claimed_ids=[903], package_lookup=lambda appid: packages[appid],
    )
    assert [(o.appid, o.package_id, o.kind, o.parent_appid) for o in offers] == [
        ("11", 901, "dlc", "1"),
    ]


# ------------------------------ обход по кругу ------------------------------

def test_scan_slice_walks_the_library_and_wraps_around(isolated_data_dir):
    library = [str(i) for i in range(1, 8)]
    seen = []
    for _ in range(4):
        chunk, position = free_games.next_scan_slice(library, limit=3)
        free_games.remember_scan_position(position)
        seen.append(chunk)
    assert seen == [["1", "2", "3"], ["4", "5", "6"], ["7", "1", "2"], ["3", "4", "5"]]


def test_scan_slice_handles_empty_library(isolated_data_dir):
    assert free_games.next_scan_slice([], limit=3) == ([], 0)


def test_scan_slice_never_repeats_a_game_within_one_pass(isolated_data_dir):
    """Библиотека короче лимита: замыкание круга не должно её дублировать.

    Раньше на списке из одной игры кусок выходил как ['70', '70', ...], и Steam
    получал повторный запрос на одну и ту же лицензию.
    """
    chunk, position = free_games.next_scan_slice(["70"], limit=40)
    assert chunk == ["70"] and position == 0

    chunk, _ = free_games.next_scan_slice(["1", "2"], limit=5)
    assert chunk == ["1", "2"] and len(chunk) == len(set(chunk))


# --------------------------------- память ---------------------------------

def test_claimed_packages_are_remembered_across_calls(isolated_data_dir):
    assert free_games.load_claimed() == set()
    free_games.remember_claimed([101, 102])
    free_games.remember_claimed([102, 103])
    assert free_games.load_claimed() == {101, 102, 103}


def test_claimed_and_scan_position_share_the_file_without_clobbering(isolated_data_dir):
    free_games.remember_claimed([7])
    free_games.remember_scan_position(42)
    assert free_games.load_claimed() == {7}
    assert free_games.load_scan_position() == 42


def test_unconfirmed_claim_is_retried_until_attempts_run_out(isolated_data_dir):
    """Просьба к Steam — ещё не выдача.

    Раньше пакет считался забранным в момент запроса: если Steam был закрыт или
    программу закрыли посреди очереди, раздача не повторялась уже никогда.
    """
    free_games.remember_attempt(300)
    assert 300 not in free_games.load_claimed(), "one failed request must not bury the offer"
    for _ in range(free_games.MAX_CLAIM_ATTEMPTS - 1):
        free_games.remember_attempt(300)
    assert 300 in free_games.load_claimed(), "a hopeless offer stops pestering Steam"


def test_confirmed_claim_clears_its_attempts(isolated_data_dir):
    free_games.remember_attempt(301)
    free_games.remember_attempt(301)
    free_games.remember_claimed([301])
    state = json.loads((isolated_data_dir / "free_games.json").read_text(encoding="utf-8"))
    assert state["claimed"] == [301]
    assert "301" not in state.get("attempts", {})


def test_free_to_play_attempts_are_not_counted(isolated_data_dir):
    """У free-to-play пакета нет (0) — счётчик на нём заблокировал бы их все."""
    for _ in range(free_games.MAX_CLAIM_ATTEMPTS + 1):
        free_games.remember_attempt(0)
    assert free_games.load_claimed() == set()


def test_corrupted_state_file_is_treated_as_empty(isolated_data_dir):
    (isolated_data_dir / "free_games.json").write_text("{сломано", encoding="utf-8")
    assert free_games.load_claimed() == set()
    assert free_games.load_scan_position() == 0


# ------------------------------ сеть недоступна ------------------------------

@pytest.mark.parametrize("error", [
    urllib.error.URLError("нет сети"),
    urllib.error.HTTPError("url", 429, "too many requests", {}, None),
    TimeoutError("истекло время ожидания"),
    OSError("сокет закрыт"),
])
def test_network_failures_never_raise(monkeypatch, error):
    def boom(request, timeout=None):
        raise error

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert free_games.fetch_offers() == []
    assert free_games.free_dlc_for_app("10") == []
    assert free_games.fetch_details("10") is None
    assert free_games.free_package_for("10") is None


def test_broken_json_never_raises(monkeypatch):
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"<html>503</html>"

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Response())
    assert free_games.fetch_offers() == []
    assert free_games.free_dlc_for_app("10") == []


def test_fetch_offers_carries_kind_and_parent(monkeypatch):
    """Сквозная проверка разбора: из выдачи и appdetails собирается FreeOffer."""
    search = {"results_html": '<a data-ds-appid="5"><span class="title">Саундтрек</span></a>'}
    details = {"5": {"success": True, "data": {
        "type": "music",
        "name": "Саундтрек",
        "fullgame": {"appid": "99", "name": "Базовая игра"},
        "package_groups": [{"subs": [
            {"packageid": 500, "is_free_license": True, "price_in_cents_with_discount": 0},
        ]}],
    }}}

    def fake_get(url, timeout=None):
        return json.dumps(details if "appdetails" in url else search)

    monkeypatch.setattr(free_games, "_get", fake_get)
    offers = free_games.fetch_offers(delay=0)
    assert len(offers) == 1
    found = offers[0]
    assert (found.appid, found.package_id, found.kind) == ("5", 500, "music")
    assert (found.parent_appid, found.parent_name) == ("99", "Базовая игра")
    assert found.needs_parent is True


# --------------------------- free-to-play без пакета ---------------------------

def f2p_payload(appid, is_free=True, kind="game", packages=None):
    return {str(appid): {"success": True, "data": {
        "type": kind,
        "name": f"Игра {appid}",
        "is_free": is_free,
        "package_groups": packages if packages is not None else [],
    }}}


def test_free_to_play_game_is_recognised_without_any_package():
    """У free-to-play package_groups пуст — покупать нечего.

    Раньше поиск пакета возвращал None, и такая игра отвергалась с «бесплатно её
    не отдают», хотя в магазине у неё кнопка «Добавить в библиотеку».
    """
    payload = f2p_payload(4212480)
    assert free_games.find_free_package(payload, "4212480") is None
    assert free_games.is_free_to_play(payload, "4212480") is True


def test_paid_game_is_not_free_to_play():
    assert free_games.is_free_to_play(f2p_payload(1, is_free=False), "1") is False


def test_free_dlc_is_not_treated_as_free_to_play():
    """steam://install по appid дополнения ничего не добавит — нужен пакет."""
    assert free_games.is_free_to_play(f2p_payload(2, kind="dlc"), "2") is False
    assert free_games.is_free_to_play(f2p_payload(3, kind="music"), "3") is False


def test_claim_url_falls_back_to_the_app_when_there_is_no_package():
    assert free_games.claim_url_for("4212480", 0) == "steam://install/4212480"
    assert free_games.claim_url_for("4212480", 777) == "steam://subscriptioninstall/777"


def test_free_to_play_offer_produces_an_install_link():
    step = free_games.ClaimStep(appid="4212480", name="Игра", package_id=0)
    assert step.claim_url == "steam://install/4212480"


def test_free_to_play_base_game_is_claimed_for_its_dlc():
    """Базовая игра тоже бывает free-to-play: пакета нет, а лицензия доступна."""
    steps, skipped = free_games.plan_claims(
        [offer(11, 101, kind="dlc", parent="99")],
        owned_appids=[],
        package_lookup=lambda appid: 0 if appid == "99" else None,
    )
    assert skipped == []
    assert [(s.appid, s.claim_url) for s in steps] == [
        ("99", "steam://install/99"),
        ("11", "steam://subscriptioninstall/101"),
    ]


def test_zero_package_is_never_remembered_as_claimed(isolated_data_dir):
    """Ноль совпал бы с любой другой free-to-play игрой и заблокировал их все."""
    free_games.remember_claimed([0, 500])
    assert free_games.load_claimed() == {500}


def test_free_to_play_offers_are_not_filtered_by_the_claimed_list():
    offers = [offer(10, 0), offer(20, 0)]
    steps, _ = free_games.plan_claims(offers, owned_appids=[], claimed_ids=[0])
    assert [s.appid for s in steps] == ["10", "20"]
