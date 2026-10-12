import gzip
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from BoostiFy.core import app_paths
from BoostiFy.core.app_paths import replace_with_retry

STEAM_APPLIST_URL = "https://raw.githubusercontent.com/dgibbs64/SteamCMD-AppID-List/master/steamcmd_appid.json"
# Официальный поиск магазина. Нужен потому, что каталог выше скачивается один раз
# и дальше лежит на диске без обновления: игра, вышедшая после первой загрузки,
# по названию не находится вообще никогда.
STORE_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
# Возраст каталога, после которого «Добавить все игры» скачивает его заново.
# Неделя: каталог весит десятки мегабайт, а новинок за день немного.
CATALOG_MAX_AGE_SEC = 7 * 24 * 3600


def search_store_exact(name, timeout=15):
    """Точное совпадение по названию через магазин Steam: (appid, имя) или None.

    Спрашиваем магазин, а не локальный каталог: он всегда актуален. Берём только
    полное совпадение имени — частичное уводило бы не туда (на «Half-Life»
    магазин первым отдаёт «Half-Life 2»).
    """
    query = _normalize_name(name)
    folded = _fold_name(name)
    if not query:
        return None
    params = urllib.parse.urlencode({"term": name, "cc": "us", "l": "english"})
    try:
        request = urllib.request.Request(
            f"{STORE_SEARCH_URL}?{params}", headers={"User-Agent": "BoostiFy"}
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        appid = item.get("id")
        title = str(item.get("name") or "")
        if not isinstance(appid, int):
            continue
        if _normalize_name(title) == query or (folded and _fold_name(title) == folded):
            return appid, title
    return None


def default_cache_file() -> Path:
    """Путь к кэшу каталога, вычисляемый в момент вызова.

    Раньше здесь на уровне модуля стояли `UPLOAD_DIR.mkdir(...)` и готовая
    константа CACHE_FILE: каталог данных создавался от одного лишь импорта, а путь
    намертво привязывался к состоянию app_paths на момент импорта — перенаправить
    хранилище (тесты, портативный режим) уже было нельзя."""
    return app_paths.DATA_DIR / "games_upload.json"


def _normalize_name(name: str) -> str:
    return " ".join(str(name or "").strip().lower().split())


def _fold_name(name: str) -> str:
    """Ключ без пунктуации и пробелов: 'Counter-Strike' и 'Counter Strike' -> 'counterstrike'.
    Позволяет находить игру, когда пользователь ввёл иначе расставленные дефисы/пробелы."""
    return "".join(filter(str.isalnum, str(name or "").lower()))


class SteamAppLookup:
    def __init__(self, allow_fetch: bool = True, cache_file=None, initial_apps=None, lazy=False):
        """lazy=True откладывает чтение кэша до первого обращения (или warm_up()).

        Каталог — это ~165 тыс. игр: чтение и индексация занимают около секунды и
        ~100 МБ памяти. Окно делало это прямо в конструкторе, в потоке интерфейса,
        и появлялось на секунду позже, «замирая» на это время."""
        self._load_lock = threading.Lock()
        self.cache_file = Path(cache_file) if cache_file is not None else default_cache_file()
        self._allow_fetch = allow_fetch
        self.apps = []
        self._rebuild_index()
        self._loaded = False
        if initial_apps is not None:
            self.apps = self._normalize_apps_payload(initial_apps)
            self._rebuild_index()
            self._loaded = True
        elif not lazy:
            self._load_initial()

    def _load_initial(self):
        cached = self.load_cache()
        if cached is None and self._allow_fetch:
            cached = self.fetch_applist()
        elif cached:
            self._compact_old_cache(cached)
        self.apps = cached or []
        self._rebuild_index()
        self._loaded = True

    def _compact_old_cache(self, apps):
        """Кэш старого формата (с отступами, ~17 МБ) один раз переписываем
        компактно (~9 МБ). Дату файла сохраняем: по ней решается, когда
        каталог пора скачивать заново."""
        try:
            with self.cache_file.open("rb") as f:
                head = f.read(16).removeprefix(b"\xef\xbb\xbf")
            if not head.startswith((b"[\n", b"[\r\n")):
                return
            stat = self.cache_file.stat()
        except OSError:
            return
        self._write_cache(apps)
        try:
            os.utime(self.cache_file, (stat.st_atime, stat.st_mtime))
        except OSError:
            pass

    def warm_up(self):
        """Загружает отложенный каталог; безопасно звать из любого потока и не раз."""
        if self._loaded:
            return
        with self._load_lock:
            if not self._loaded:
                self._load_initial()

    def clear(self):
        """Забыть каталог в памяти (после удаления его кэша с диска)."""
        with self._load_lock:
            self.apps = []
            self._rebuild_index()
            self._loaded = True

    def ensure_loaded(self, max_age=None) -> bool:
        """Каталог в памяти; max_age (секунды) заодно обновляет устаревший.

        Без max_age каталог, скачанный однажды, жил на диске вечно, и игры,
        вышедшие позже, «Добавить все игры» не видела никогда: она проверяет
        владение ровно по этому списку. Не удалось обновить — работаем со старым.
        """
        self.warm_up()
        if self.apps and not self._is_stale(max_age):
            return True
        with self._load_lock:
            if self.apps and not self._is_stale(max_age):
                return True
            fresh = self.fetch_applist()
            if fresh:
                self.apps = fresh
                self._rebuild_index()
        return bool(self.apps)

    def _is_stale(self, max_age) -> bool:
        if max_age is None:
            return False
        try:
            age = time.time() - self.cache_file.stat().st_mtime
        except OSError:
            # Файла нет, а каталог в памяти есть (подан напрямую) — освежать нечего.
            return False
        return age > max_age

    def _rebuild_index(self):
        # Нормализуем имена ОДИН раз: точный индекс имя->appid, обратный appid->name,
        # и список пред-нормализованных имён для подстрочного поиска — чтобы не
        # нормализовать ~200k имён заново на каждый вызов find_appid/find_similar.
        # Индексы собираются в локальных переменных и подменяются разом: поиск из
        # фонового потока не застанет их наполовину построенными.
        exact_index = {}
        folded_index = {}
        appid_index = {}
        normalized = []
        for app in self.apps:
            if not isinstance(app, dict):
                continue
            appid = app.get("appid")
            if appid is None:
                continue
            raw_name = app.get("name") or ""
            # Ключ — число, а не str(appid): это ~165 тыс. лишних строк (~8 МБ).
            try:
                appid_index[int(appid)] = raw_name
            except (TypeError, ValueError):
                pass
            norm = _normalize_name(raw_name)
            if norm:
                exact_index.setdefault(norm, appid)
                normalized.append((norm, appid, app))
            folded = _fold_name(raw_name)
            if folded:
                folded_index.setdefault(folded, appid)
        self._exact_index = exact_index
        self._folded_index = folded_index
        self._appid_index = appid_index
        self._normalized = normalized

    def get_name(self, appid) -> str | None:
        """Имя игры по appid за O(1) (обратный индекс), либо None."""
        self.warm_up()
        try:
            key = int(str(appid))
        except (TypeError, ValueError):
            return None
        return self._appid_index.get(key) or None

    def fetch_applist(self):
        # stdlib вместо requests: единственный HTTP-вызов в проекте не стоит зависимости.
        # urlopen сам поднимает HTTPError на 4xx/5xx, поэтому raise_for_status не нужен.
        try:
            request = urllib.request.Request(
                STEAM_APPLIST_URL,
                headers={"User-Agent": "BoostiFy/1.0", "Accept-Encoding": "gzip"},
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read()
                # requests распаковывал gzip сам; каталог Steam весит десятки МБ,
                # поэтому сжатие запрашиваем явно и разжимаем руками.
                if response.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
            # utf-8-sig: снимает BOM, если он есть, и не мешает, если его нет.
            apps = self._normalize_apps_payload(json.loads(raw.decode("utf-8-sig")))
            if apps:  # не кешируем пустой/битый ответ, иначе он подменит валидный кэш
                self._write_cache(apps)
            return apps
        except Exception as e:
            print(f"Ошибка загрузки списка Steam: {e}")
            return []

    def load_cache(self):
        apps = self._read_cache(self.cache_file)
        return apps or None

    def find_appid(self, name: str) -> int | None:
        self.warm_up()
        exact = self.find_exact_appid(name)
        if exact is not None:
            return exact

        query = _normalize_name(name)
        if not query:
            return None

        for norm, appid, _app in self._normalized:
            if query in norm:
                return appid

        return None

    def find_exact_appid(self, name: str) -> int | None:
        """Resolve only an unambiguous exact name, including punctuation folding."""
        self.warm_up()
        query = _normalize_name(name)
        if not query:
            return None
        exact = self._exact_index.get(query)
        if exact is not None:
            return exact
        folded = _fold_name(name)
        return self._folded_index.get(folded) if folded else None

    def find_similar(self, name: str, limit: int = 5) -> list[dict]:
        self.warm_up()
        query = _normalize_name(name)
        if not query:
            return []

        starts = []
        contains = []
        seen = set()
        for norm, appid, app in self._normalized:
            if appid in seen:
                continue
            if norm.startswith(query):
                starts.append(app)
                seen.add(appid)
            elif query in norm:
                contains.append(app)
                seen.add(appid)
            if len(starts) >= limit:
                break

        return (starts + contains)[:limit]

    def _read_cache(self, path: Path):
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8-sig") as f:
                return self._normalize_apps_payload(json.load(f))
        except Exception:
            return None

    def _write_cache(self, apps):
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.cache_file.with_name(
            f"{self.cache_file.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            # Без отступов и без поля status (его заново ставит
            # _normalize_apps_payload при чтении): с indent=2 каталог весил ~17 МБ.
            compact = [{"appid": app["appid"], "name": app["name"]} for app in apps]
            with temp_file.open("w", encoding="utf-8") as f:
                json.dump(compact, f, ensure_ascii=False, separators=(",", ":"))
            replace_with_retry(temp_file, self.cache_file)
        except OSError as e:
            print(f"Не удалось обновить кеш Steam AppID: {e}")
        finally:
            try:
                temp_file.unlink(missing_ok=True)
            except OSError:
                pass

    def _normalize_apps_payload(self, data):
        if isinstance(data, dict) and "applist" in data and "apps" in data["applist"]:
            raw_apps = data["applist"]["apps"]
        elif isinstance(data, list):
            raw_apps = data
        else:
            return []
        if not isinstance(raw_apps, list):
            return []

        normalized = []
        seen = set()
        for raw in raw_apps[:1_000_000]:
            if isinstance(raw, dict):
                appid = raw.get("appid")
                name = raw.get("name", "")
            elif isinstance(raw, (str, int)):
                appid = raw
                name = ""
            else:
                continue

            try:
                appid = int(appid)
            except (TypeError, ValueError):
                continue
            if appid <= 0 or appid in seen:
                continue

            seen.add(appid)
            normalized.append({
                "appid": appid,
                "name": str(name or "")[:300],
                "status": "Готово",
            })
        return normalized


if __name__ == "__main__":
    lookup = SteamAppLookup()
    print("AppID Counter-Strike:", lookup.find_appid("Counter-Strike"))
