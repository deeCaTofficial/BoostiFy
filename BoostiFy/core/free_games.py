"""Поиск бесплатных раздач в Steam и выдача лицензий на них.

Steam иногда отдаёт платные позиции со 100% скидкой — «Limited Free Promotional
Package». Забрать такую лицензию можно один раз, и дальше она остаётся в аккаунте
навсегда. Здесь мы находим такие позиции в магазине и просим запущенный
Steam-клиент добавить пакет.

Пароли и cookie не нужны: клиент уже авторизован, а ссылка steam:// — его
собственный протокол. Наружу уходят только GET-запросы к публичному магазину.
"""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from BoostiFy.core import app_paths
from BoostiFy.core.app_paths import replace_with_retry

SEARCH_URL = "https://store.steampowered.com/search/results/"
APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
# Все дополнения игры одним запросом: у бесплатного нет price_overview.
DLC_FOR_APP_URL = "https://store.steampowered.com/api/dlcforapp/"
CLAIM_URL_TEMPLATE = "steam://subscriptioninstall/{package_id}"
# Free-to-play отдаётся без пакета: у таких игр package_groups пуст, и лицензию
# добавляет сам клиент по appid — это и делает кнопка «Добавить в библиотеку».
FREE_APP_URL_TEMPLATE = "steam://install/{appid}"

REQUEST_TIMEOUT = 20
# Пауза между запросами к магазину: у него лимит порядка 200 запросов за 5 минут.
REQUEST_DELAY = 0.4
# Сколько позиций разбираем максимум — страховка от неожиданно огромной выдачи.
MAX_OFFERS = 60
# Сколько игр библиотеки опрашиваем за один проход. Библиотека бывает в тысячи
# позиций: полный обход занял бы часы, поэтому идём по кругу, запоминая место.
LIBRARY_SCAN_LIMIT = 40
# Сколько раз просить Steam об одной раздаче, прежде чем отступиться. Раз — мало:
# Steam мог быть закрыт или перезапускаться. Бесконечно — тоже нельзя: раздачу,
# недоступную в регионе, клиент отклонял бы своим окном каждые полчаса.
MAX_CLAIM_ATTEMPTS = 3

_USER_AGENT = "BoostiFy"
_ROW_RE = re.compile(r'data-ds-appid="(\d+)"[\s\S]*?<span class="title">([^<]*)</span>')


@dataclass(frozen=True)
class FreeOffer:
    """Раздача: что забирать и как это назвать человеку.

    kind — что это за продукт по версии магазина: game, dlc, music. Для всего,
    кроме game, нужна родительская игра: без неё дополнение не откроется, а
    саундтрек не появится в библиотеке.
    """

    appid: str
    name: str
    package_id: int
    kind: str = "game"
    parent_appid: str = ""
    parent_name: str = ""

    @property
    def claim_url(self) -> str:
        return claim_url_for(self.appid, self.package_id)

    @property
    def needs_parent(self) -> bool:
        return self.kind != "game" and bool(self.parent_appid)


@dataclass(frozen=True)
class ClaimStep:
    """Одна выдача лицензии. reason объясняет, почему она в очереди."""

    appid: str
    name: str
    package_id: int
    reason: str = "offer"   # offer — сама раздача, parent — игра ради дополнения

    @property
    def claim_url(self) -> str:
        return claim_url_for(self.appid, self.package_id)


def claim_url_for(appid, package_id) -> str:
    """Ссылка на выдачу: по пакету, а при его отсутствии — по самому приложению.

    package_id = 0 означает free-to-play: пакета у такой игры нет вовсе, и клиент
    заводит лицензию по appid.
    """
    if package_id:
        return CLAIM_URL_TEMPLATE.format(package_id=package_id)
    return FREE_APP_URL_TEMPLATE.format(appid=appid)


def _get(url, timeout=REQUEST_TIMEOUT):
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


# --------------------------------- поиск раздач ---------------------------------

def search_url(include_extras: bool = True, count: int = MAX_OFFERS) -> str:
    """Ссылка на выдачу магазина: платное со скидкой 100%.

    include_extras=False добавляет category1=998 и оставляет только игры. Такой
    фильтр почти всегда пуст: раздают в основном дополнения и саундтреки.
    """
    params = {
        "maxprice": "free",   # итоговая цена 0
        "specials": "1",      # ...именно из-за скидки, а не потому что f2p
        "ndl": "1",
        "hwtype": "0",
        "infinite": "1",      # выдача приходит JSON-ом, а не целой страницей
        "json": "1",
        "start": "0",
        "count": str(max(1, int(count))),
        "cc": "us",
        "l": "english",
    }
    if not include_extras:
        params["category1"] = "998"
    return SEARCH_URL + "?" + urllib.parse.urlencode(params)


def parse_search_results(payload):
    """[(appid, название)] из ответа магазина. Чужой формат -> пустой список."""
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except ValueError:
            return []
    if not isinstance(payload, dict):
        return []
    html = payload.get("results_html")
    if not isinstance(html, str):
        return []
    seen = set()
    rows = []
    for appid, name in _ROW_RE.findall(html):
        if appid in seen:
            continue
        seen.add(appid)
        rows.append((appid, name.strip()))
    return rows[:MAX_OFFERS]


def find_free_package(details_payload, appid):
    """ID дарового пакета из ответа appdetails, либо None.

    Опознаём по полям, а не по подписи: у промо-пакета is_free_license=True и
    нулевая цена, тогда как платный вариант того же продукта лежит в том же
    списке. Разбирать option_text нельзя — он локализуется и меняется.
    """
    if not isinstance(details_payload, dict):
        return None
    node = details_payload.get(str(appid))
    if not isinstance(node, dict) or not node.get("success"):
        return None
    data = node.get("data")
    if not isinstance(data, dict):
        return None
    for group in data.get("package_groups") or []:
        if not isinstance(group, dict):
            continue
        for sub in group.get("subs") or []:
            if not isinstance(sub, dict):
                continue
            package_id = sub.get("packageid")
            if not isinstance(package_id, int):
                continue
            if sub.get("is_free_license") and sub.get("price_in_cents_with_discount") == 0:
                return package_id
    return None


def fetch_details(appid, timeout=REQUEST_TIMEOUT):
    """Ответ appdetails по одному приложению, либо None.

    По одному, потому что пачкой Steam больше не отвечает: appids=1,2,3 отдаёт
    400 Bad Request.
    """
    query = urllib.parse.urlencode({"appids": appid, "cc": "us", "l": "english"})
    try:
        return json.loads(_get(f"{APPDETAILS_URL}?{query}", timeout))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None


def describe_app(details_payload, appid):
    """Тип продукта и его родитель из ответа appdetails."""
    empty = {"kind": "game", "parent_appid": "", "parent_name": "", "name": ""}
    if not isinstance(details_payload, dict):
        return empty
    node = details_payload.get(str(appid))
    if not isinstance(node, dict) or not node.get("success"):
        return empty
    data = node.get("data")
    if not isinstance(data, dict):
        return empty
    parent = data.get("fullgame") if isinstance(data.get("fullgame"), dict) else {}
    return {
        "kind": str(data.get("type") or "game"),
        "parent_appid": str(parent.get("appid") or ""),
        "parent_name": str(parent.get("name") or ""),
        "name": str(data.get("name") or ""),
    }


def free_package_for(appid, timeout=REQUEST_TIMEOUT):
    """ID дарового пакета приложения, либо None, если даром его не отдают."""
    return find_free_package(fetch_details(appid, timeout), appid)


def is_free_to_play(details_payload, appid) -> bool:
    """Игра раздаётся бесплатно сама по себе, без промо-пакета."""
    if not isinstance(details_payload, dict):
        return False
    node = details_payload.get(str(appid))
    if not isinstance(node, dict) or not node.get("success"):
        return False
    data = node.get("data")
    if not isinstance(data, dict) or not data.get("is_free"):
        return False
    # Дополнению и саундтреку одного is_free мало: их лицензия живёт в пакете, и
    # steam://install по такому appid ничего не добавит.
    return str(data.get("type") or "game") == "game"


def free_acquisition_for(appid, timeout=REQUEST_TIMEOUT):
    """Как получить приложение даром: ID пакета, 0 для free-to-play, None — никак.

    Раньше здесь был только поиск пакета, и free-to-play игры отвергались с
    «бесплатно её не отдают», хотя в магазине у них стоит «Добавить в библиотеку»:
    package_groups у таких игр пуст, потому что покупать нечего.
    """
    payload = fetch_details(appid, timeout)
    if payload is None:
        return None
    package_id = find_free_package(payload, appid)
    if package_id is not None:
        return package_id
    return 0 if is_free_to_play(payload, appid) else None


def fetch_offers(include_extras: bool = True, timeout=REQUEST_TIMEOUT, delay=REQUEST_DELAY):
    """Текущие раздачи. Любая помеха -> пустой список, без исключений.

    Недоступный магазин, изменившийся формат, отсутствие сети — не повод ронять
    буст, внутри которого нас и вызывают.
    """
    try:
        results = parse_search_results(_get(search_url(include_extras), timeout))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return []

    offers = []
    for index, (appid, name) in enumerate(results):
        if index and delay:
            time.sleep(delay)
        payload = fetch_details(appid, timeout)
        if payload is None:
            continue
        package_id = find_free_package(payload, appid)
        if package_id is None:
            continue
        info = describe_app(payload, appid)
        offers.append(FreeOffer(
            appid=str(appid),
            name=name or info["name"],
            package_id=package_id,
            kind=info["kind"],
            parent_appid=info["parent_appid"],
            parent_name=info["parent_name"],
        ))
    return offers


# ------------------------- дополнения к своим играм -------------------------

def parse_free_dlc(payload):
    """Бесплатные позиции из ответа dlcforapp. Чужой формат -> пустой список."""
    if not isinstance(payload, dict) or not isinstance(payload.get("dlc"), list):
        return []
    free = []
    for item in payload["dlc"]:
        if not isinstance(item, dict):
            continue
        dlc_id = item.get("id")
        if not isinstance(dlc_id, int):
            continue
        price = item.get("price_overview")
        # Блока цены нет вовсе — позиция бесплатна. Если блок есть, берём её
        # только при нулевой итоговой цене (та же раздача, но с ценником).
        if price is None or (isinstance(price, dict) and price.get("final") == 0):
            free.append((str(dlc_id), str(item.get("name") or dlc_id)))
    return free


def free_dlc_for_app(appid, timeout=REQUEST_TIMEOUT):
    """Бесплатные дополнения игры: [(appid, название)]. Один запрос на игру."""
    query = urllib.parse.urlencode({"appid": appid})
    try:
        payload = json.loads(_get(f"{DLC_FOR_APP_URL}?{query}", timeout))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return []
    return parse_free_dlc(payload)


def scan_owned_for_free_dlc(appids, limit=LIBRARY_SCAN_LIMIT, delay=REQUEST_DELAY,
                            dlc_lookup=None):
    """Бесплатные дополнения своих игр: ([(appid, название, родитель)], опрошено).

    Идём от библиотеки, а не от общего списка бесплатных дополнений: их в магазине
    больше четырёх тысяч, и родителя каждого пришлось бы спрашивать отдельным
    запросом. От библиотеки один запрос отдаёт все дополнения игры сразу.

    limit ограничивает проход: остаток доберём в следующий раз, с того же места.
    """
    lookup = dlc_lookup or free_dlc_for_app
    found = []
    scanned = 0
    for appid in appids:
        if limit is not None and scanned >= limit:
            break
        if scanned and delay:
            time.sleep(delay)
        scanned += 1
        for dlc_appid, dlc_name in lookup(str(appid)):
            found.append((str(dlc_appid), dlc_name, str(appid)))
    return found, scanned


def resolve_dlc_offers(candidates, claimed_ids=(), package_lookup=None):
    """Оставляет кандидатов, у которых действительно есть даровой пакет.

    Отдельным шагом, потому что между поиском и этим местом должна встать проверка
    владения: спрашивать пакет для каждого найденного дополнения — лишние запросы,
    а большинство из них уже лежит в аккаунте.
    """
    lookup = package_lookup or free_package_for
    claimed = set(claimed_ids or ())
    offers = []
    for dlc_appid, dlc_name, parent_appid in candidates:
        package_id = lookup(str(dlc_appid))
        if package_id is None or package_id in claimed:
            continue
        offers.append(FreeOffer(
            appid=str(dlc_appid),
            name=dlc_name,
            package_id=package_id,
            kind="dlc",
            parent_appid=str(parent_appid),
        ))
    return offers


# ------------------------------- что и как забирать -------------------------------

def plan_claims(offers, owned_appids=(), claimed_ids=(), package_lookup=None):
    """Что и в каком порядке просить у Steam. Возвращает (шаги, свёрнутое).

    Дополнение или саундтрек без родительской игры бесполезны: лицензия ляжет в
    аккаунт, но открывать будет нечего. Поэтому сначала проверяем саму игру, и
    если её нет — пробуем взять и её. Не выходит (игра платная) — сворачиваем всю
    связку целиком.

    package_lookup подменяется в тестах, чтобы обойтись без сети.
    """
    # free_acquisition_for, а не free_package_for: базовая игра тоже бывает
    # free-to-play, и тогда пакета у неё нет, а лицензия всё равно доступна.
    lookup = package_lookup or free_acquisition_for
    owned = {str(value) for value in (owned_appids or ())}
    claimed = set(claimed_ids or ())
    steps = []
    skipped = []
    queued_parents = set()

    for offer in offers:
        if (offer.package_id and offer.package_id in claimed) or str(offer.appid) in owned:
            continue
        if offer.needs_parent:
            parent = str(offer.parent_appid)
            if parent not in owned and parent not in queued_parents:
                parent_package = lookup(parent)
                if parent_package is None:
                    skipped.append((offer, "нет базовой игры, и даром её не отдают"))
                    continue
                steps.append(ClaimStep(
                    appid=parent,
                    name=offer.parent_name or parent,
                    package_id=parent_package,
                    reason="parent",
                ))
                queued_parents.add(parent)
        steps.append(ClaimStep(
            appid=str(offer.appid),
            name=offer.name,
            package_id=offer.package_id,
            reason="offer",
        ))
    return steps, skipped


# --------------------------------- память ---------------------------------

def _state_file():
    """Путь считаем в момент вызова: app_paths.DATA_DIR подменяется в тестах."""
    return app_paths.DATA_DIR / "free_games.json"


def _load_state():
    try:
        with open(_state_file(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(state) -> bool:
    path = _state_file()
    temporary = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False)
        replace_with_retry(temporary, path)
    except OSError:
        return False
    return True


def _attempts(state) -> dict:
    raw = state.get("attempts")
    if not isinstance(raw, dict):
        return {}
    return {
        int(key): value for key, value in raw.items()
        if str(key).isdigit() and isinstance(value, int) and value > 0
    }


def load_claimed() -> set:
    """ID пакетов, о которых Steam больше не спрашиваем.

    Это забранные (выдачу подтвердил Steam) и безнадёжные — те, что Steam не
    выдал MAX_CLAIM_ATTEMPTS раз подряд. Чтобы повторная проверка во время
    долгой сессии не дёргала клиент из-за одной и той же раздачи каждые полчаса.
    """
    state = _load_state()
    claimed = {value for value in state.get("claimed", []) if isinstance(value, int)}
    exhausted = {
        package for package, count in _attempts(state).items()
        if count >= MAX_CLAIM_ATTEMPTS
    }
    return claimed | exhausted


def remember_claimed(package_ids) -> bool:
    """Отмечает пакеты, выдачу которых подтвердил Steam."""
    state = _load_state()
    # Ноль — это free-to-play без пакета: запоминать нечего, а в множестве он бы
    # совпал с любой другой такой же игрой и заблокировал их все разом.
    confirmed = {int(value) for value in package_ids if int(value) > 0}
    if not confirmed:
        return True
    claimed = {value for value in state.get("claimed", []) if isinstance(value, int)}
    state["claimed"] = sorted(claimed | confirmed)
    attempts = _attempts(state)
    for package in confirmed:
        attempts.pop(package, None)
    state["attempts"] = {str(key): value for key, value in sorted(attempts.items())}
    return _save_state(state)


def remember_attempt(package_id) -> bool:
    """Засчитывает ещё одну просьбу к Steam выдать пакет."""
    try:
        package_id = int(package_id)
    except (TypeError, ValueError):
        return False
    if package_id <= 0:
        return True
    state = _load_state()
    attempts = _attempts(state)
    attempts[package_id] = attempts.get(package_id, 0) + 1
    state["attempts"] = {str(key): value for key, value in sorted(attempts.items())}
    return _save_state(state)


def load_scan_position() -> int:
    """С какой позиции библиотеки продолжать обход дополнений."""
    value = _load_state().get("scan_position")
    return value if isinstance(value, int) and value >= 0 else 0


def remember_scan_position(value) -> bool:
    state = _load_state()
    state["scan_position"] = max(0, int(value))
    return _save_state(state)


def next_scan_slice(appids, limit=LIBRARY_SCAN_LIMIT):
    """Кусок библиотеки для очередного прохода и позиция после него.

    Обход идёт по кругу: дошли до конца — начинаем сначала. Раздачи появляются в
    любой момент, поэтому одного полного прохода мало.
    """
    appids = [str(value) for value in appids]
    if not appids:
        return [], 0
    # Не больше одного полного круга за проход: иначе на библиотеке короче лимита
    # замыкание подставляло одни и те же игры по нескольку раз, и Steam получал
    # повторные запросы на одну и ту же лицензию.
    limit = min(max(1, int(limit)), len(appids))
    start = load_scan_position() % len(appids)
    chunk = appids[start:start + limit]
    if len(chunk) < limit:
        chunk += appids[:limit - len(chunk)]   # замыкаем круг
    return chunk, (start + len(chunk)) % len(appids)
