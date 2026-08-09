"""Проверка новой версии на GitHub.

Спрашиваем у GitHub последний опубликованный релиз и сравниваем его номер с
версией, которая сейчас запущена. Ошибка сети, недоступный GitHub, изменившийся
ответ API — всё это не повод беспокоить пользователя: проверка молча
возвращает None, программа работает как обычно.
"""

import json
import os
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from BoostiFy import __version__
from BoostiFy.core import app_paths
from BoostiFy.core.app_paths import replace_with_retry

REPOSITORY = "deeCaTofficial/BoostiFy"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
REQUEST_TIMEOUT = 8

# Полное отключение проверки. Нужно тем, у кого исходящие соединения закрыты
# политикой или просто не хочется лишнего запроса, и всем автоматическим прогонам:
# иначе тесты стучались бы в GitHub и упирались в лимит запросов.
DISABLE_ENV_VAR = "BOOSTIFY_NO_UPDATE_CHECK"

# Номер версии: 1.1.2, v1.1.2, 1.1.2-beta1. Суффикс после цифр отбрасываем — он не
# участвует в сравнении, но и не мешает распознать сам номер.
_VERSION_RE = re.compile(r"v?(\d+(?:\.\d+)*)")


@dataclass(frozen=True)
class UpdateInfo:
    """Найденная новая версия."""

    version: str
    url: str
    current: str = __version__


def parse_version(text):
    """'v1.1.2' -> (1, 1, 2). Неразбираемое значение -> None."""
    match = _VERSION_RE.match(str(text or "").strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(candidate, current) -> bool:
    """Строго ли candidate новее current.

    Кортежи разной длины дополняем нулями: 1.2 и 1.2.0 — одна и та же версия, а
    без выравнивания (1, 2) < (1, 2, 0) и программа предложила бы «обновиться»
    на то, что уже установлено.
    """
    left, right = parse_version(candidate), parse_version(current)
    if left is None or right is None:
        return False
    length = max(len(left), len(right))
    left += (0,) * (length - len(left))
    right += (0,) * (length - len(right))
    return left > right


def _state_file() -> Path:
    """Путь вычисляем в момент вызова: app_paths.DATA_DIR подменяется в тестах."""
    return app_paths.DATA_DIR / "update_state.json"


def load_skipped_version() -> str:
    """Версия, о которой пользователь уже сказал «Позже»."""
    try:
        with open(_state_file(), encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return ""
    return str(data.get("skipped_version", "")) if isinstance(data, dict) else ""


def remember_skipped_version(version) -> bool:
    """Запоминает отклонённую версию, чтобы не спрашивать о ней при каждом запуске.

    Пишем через временный файл и replace_with_retry — как и остальные данные:
    антивирус или индексатор Windows может держать файл открытым.
    """
    path = _state_file()
    temporary = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump({"skipped_version": str(version or "")}, handle, ensure_ascii=False)
        replace_with_retry(temporary, path)
    except OSError:
        return False
    return True


def fetch_latest_release(timeout=REQUEST_TIMEOUT):
    """Последний релиз с GitHub: (номер версии, ссылка на страницу). Иначе None.

    /releases/latest на стороне GitHub уже отсекает черновики и предрелизы, так
    что фильтровать их повторно не нужно. User-Agent обязателен: без него API
    отвечает 403.
    """
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "User-Agent": f"BoostiFy/{__version__}",
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    tag = str(payload.get("tag_name") or "").strip()
    if not tag or parse_version(tag) is None:
        return None
    url = str(payload.get("html_url") or "").strip()
    # Ссылку берём из ответа, но принимаем только github.com: html_url приходит
    # снаружи, и открывать в браузере произвольный адрес из ответа нельзя.
    if not url.startswith(f"https://github.com/{REPOSITORY}/"):
        url = RELEASES_PAGE
    return tag, url


def checks_disabled() -> bool:
    return bool(str(os.environ.get(DISABLE_ENV_VAR, "")).strip())


def check_for_update(current_version=__version__, timeout=REQUEST_TIMEOUT, respect_skip=True):
    """UpdateInfo, если на GitHub лежит версия новее текущей, иначе None."""
    if checks_disabled():
        return None
    latest = fetch_latest_release(timeout=timeout)
    if latest is None:
        return None
    tag, url = latest
    if not is_newer(tag, current_version):
        return None
    if respect_skip and load_skipped_version() == tag:
        return None
    return UpdateInfo(version=tag, url=url, current=str(current_version))


def check_in_background(callback, current_version=__version__):
    """Проверка в отдельном потоке для случаев без Qt (например, CLI-скриптов).

    В GUI используется BackgroundTask: он умеет отменяться и доставляет результат
    сигналом в поток интерфейса.
    """
    def worker():
        callback(check_for_update(current_version=current_version))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread
