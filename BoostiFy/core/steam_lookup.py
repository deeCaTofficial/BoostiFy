import json
import os
import threading
import uuid
from pathlib import Path
from typing import Optional

import requests

from BoostiFy.core.app_paths import DATA_DIR


STEAM_APPLIST_URL = "https://raw.githubusercontent.com/dgibbs64/SteamCMD-AppID-List/master/steamcmd_appid.json"

UPLOAD_DIR = DATA_DIR
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

CACHE_FILE = UPLOAD_DIR / "games_upload.json"


def _normalize_name(name: str) -> str:
    return " ".join(str(name or "").strip().lower().split())


def _fold_name(name: str) -> str:
    """Ключ без пунктуации и пробелов: 'Counter-Strike' и 'Counter Strike' -> 'counterstrike'.
    Позволяет находить игру, когда пользователь ввёл иначе расставленные дефисы/пробелы."""
    return "".join(ch for ch in str(name or "").lower() if ch.isalnum())


class SteamAppLookup:
    def __init__(self, allow_fetch: bool = True, cache_file=None, initial_apps=None):
        self._load_lock = threading.Lock()
        self.cache_file = Path(cache_file) if cache_file is not None else CACHE_FILE
        cached = self._normalize_apps_payload(initial_apps) if initial_apps is not None else self.load_cache()
        if cached is None and allow_fetch:
            cached = self.fetch_applist()
        self.apps = cached or []
        self._rebuild_index()

    def ensure_loaded(self) -> bool:
        if self.apps:
            return True
        with self._load_lock:
            if self.apps:
                return True
            self.apps = self.fetch_applist()
            self._rebuild_index()
        return bool(self.apps)

    def _rebuild_index(self):
        # Нормализуем имена ОДИН раз: точный индекс имя->appid, обратный appid->name,
        # и список пред-нормализованных имён для подстрочного поиска — чтобы не
        # нормализовать ~200k имён заново на каждый вызов find_appid/find_similar.
        self._exact_index = {}
        self._folded_index = {}
        self._appid_index = {}
        self._normalized = []
        for app in self.apps:
            if not isinstance(app, dict):
                continue
            appid = app.get("appid")
            if appid is None:
                continue
            raw_name = app.get("name") or ""
            self._appid_index[str(appid)] = raw_name
            norm = _normalize_name(raw_name)
            if norm:
                self._exact_index.setdefault(norm, appid)
                self._normalized.append((norm, appid, app))
            folded = _fold_name(raw_name)
            if folded:
                self._folded_index.setdefault(folded, appid)

    def get_name(self, appid) -> Optional[str]:
        """Имя игры по appid за O(1) (обратный индекс), либо None."""
        return self._appid_index.get(str(appid)) or None

    def fetch_applist(self):
        try:
            resp = requests.get(
                STEAM_APPLIST_URL,
                timeout=20,
                headers={"User-Agent": "BoostiFy/1.0"},
            )
            resp.raise_for_status()
            apps = self._normalize_apps_payload(resp.json())
            if apps:  # не кешируем пустой/битый ответ, иначе он подменит валидный кэш
                self._write_cache(apps)
            return apps
        except Exception as e:
            print(f"Ошибка загрузки списка Steam: {e}")
            return []

    def load_cache(self):
        apps = self._read_cache(self.cache_file)
        return apps or None

    def find_appid(self, name: str) -> Optional[int]:
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

    def find_exact_appid(self, name: str) -> Optional[int]:
        """Resolve only an unambiguous exact name, including punctuation folding."""
        query = _normalize_name(name)
        if not query:
            return None
        exact = self._exact_index.get(query)
        if exact is not None:
            return exact
        folded = _fold_name(name)
        return self._folded_index.get(folded) if folded else None

    def find_similar(self, name: str, limit: int = 5) -> list[dict]:
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
            with temp_file.open("w", encoding="utf-8") as f:
                json.dump(apps, f, ensure_ascii=False, indent=2)
            temp_file.replace(self.cache_file)
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
