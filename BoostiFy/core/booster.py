import heapq
import json
import os
import queue
import random
import subprocess
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from datetime import datetime

from BoostiFy.core import process_group
from BoostiFy.core.app_paths import DATA_DIR, replace_with_retry
from BoostiFy.core.runtime_paths import BACKGROUND_WORKER, OWNERSHIP_WORKER

BOOST_WORKER_PATH = str(BACKGROUND_WORKER)
OWNERSHIP_WORKER_PATH = str(OWNERSHIP_WORKER)

# Демоны буста запускаем с пониженным приоритетом: до 60 процессов одновременно,
# и BELOW_NORMAL не даёт им «задушить» передний план пользователя (для успеха буста
# приоритет не важен — таймеры грубые, минимум 30с). Только для процессов буста,
# НЕ для сервера проверки владения (он короткий и латентно-чувствительный).
_LOW_PRIORITY_KWARGS = {}
if os.name == "nt":
    _LOW_PRIORITY_KWARGS = {
        "creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS
        | subprocess.CREATE_NO_WINDOW
    }
elif os.name == "posix":
    _LOW_PRIORITY_KWARGS = {"preexec_fn": lambda: os.nice(10)}


# Столько AppID принимает за раз C#-сервер (MaximumBatchSize в OwnershipProtocol.cs).
SERVER_BATCH_LIMIT = 500

# Коды возврата воркера. Успех: 0 и 42.
SUCCESS_EXIT_CODES = frozenset({0, 42})
# В чёрный список игра попадает ТОЛЬКО за собственную, воспроизводимую проблему.
# Раньше туда уходил любой ненулевой код, поэтому единственный «моргнувший» Steam
# (код -1) или отсутствие ключа в реестре (101) хоронили игру навсегда — при том,
# что к самой игре это отношения не имеет.
GAME_UNAVAILABLE_EXIT_CODE = 3
PERMANENT_FAILURE_CODES = frozenset({GAME_UNAVAILABLE_EXIT_CODE})
_EXIT_CODE_HINTS = {
    -1: "Steam не ответил (не запущен или перезапускается)",
    1: "неверные аргументы запуска воркера",
    2: "не удалось сохранить достижения",
    GAME_UNAVAILABLE_EXIT_CODE: "игра недоступна для буста (нет в аккаунте или неверный AppID)",
    101: "Steam не найден в реестре Windows",
}


def signed_exit_code(code):
    """Код возврата в знаковом виде.

    Windows отдаёт его беззнаковым DWORD: воркер вернул -1, а subprocess показывает
    4294967295. Без приведения таблица подсказок промахивалась мимо самого частого
    сбоя («Steam не запущен»), и пользователь видел сырое число.
    """
    try:
        code = int(code)
    except (TypeError, ValueError):
        return None
    return code - 0x100000000 if code > 0x7FFFFFFF else code


def describe_exit_code(code) -> str:
    normalized = signed_exit_code(code)
    hint = _EXIT_CODE_HINTS.get(normalized)
    return f"{hint} (код {normalized})" if hint else f"exit code {normalized if normalized is not None else code}"


def get_upload_dir():
    upload_dir = str(DATA_DIR)
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def get_list_path(filename):
    return os.path.join(get_upload_dir(), filename)


def load_json_list(path):
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _atomic_dump(path, data):
    """Атомарная запись JSON: temp -> replace с повторами. Обрыв не оставит битый файл."""
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        replace_with_retry(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def build_name_map():
    """appid -> name, построенный ОДИН раз из user_games.json (источник бустящихся игр).
    Заменяет прежний get_game_name, который читал файлы с диска на КАЖДУЮ игру (O(n²) I/O)."""
    name_map = {}
    for game in load_json_list(get_list_path("user_games.json")):
        if isinstance(game, dict):
            appid = str(game.get("appid", ""))
            name = game.get("name")
            if appid and name and appid not in name_map:
                name_map[appid] = name
    return name_map


class StatusListFile:
    """Накопитель white/black-списка с буферизацией записи.

    Прежний append_unique_status на КАЖДУЮ завершённую игру перечитывал и переписывал
    весь файл целиком — это O(n²) по вводу-выводу: замер дал 1.5с на 200 записей,
    25.5с на 1600, то есть ~30 минут чистого I/O на библиотеке в 13 тысяч игр, причём
    под общим локом, сериализующим все слоты.

    Теперь содержимое живёт в памяти (проверка дубликатов — O(1) по множеству), а на
    диск сбрасывается не чаще раза в flush_interval секунд плюс принудительно в конце
    сессии. Формат файла не меняется.
    """

    def __init__(self, path, flush_interval=5.0):
        self.path = path
        self._lock = threading.Lock()
        self._items = load_json_list(path)
        self._seen = {
            str(entry.get("appid"))
            for entry in self._items
            if isinstance(entry, dict) and entry.get("appid") is not None
        }
        self._dirty = False
        self._flush_interval = flush_interval
        self._last_flush = time.monotonic()

    def known_appids(self) -> set:
        with self._lock:
            return set(self._seen)

    def add(self, appid, name, status) -> bool:
        with self._lock:
            key = str(appid)
            if key in self._seen:
                return False
            self._items.append({"appid": key, "name": name, "status": status})
            self._seen.add(key)
            self._dirty = True
            now = time.monotonic()
            if now - self._last_flush >= self._flush_interval:
                self._flush_locked(now)
            return True

    def flush(self):
        with self._lock:
            self._flush_locked(time.monotonic())

    def _flush_locked(self, now):
        if not self._dirty:
            return
        try:
            _atomic_dump(self.path, self._items)
        except OSError as error:
            log_with_time("error", None, f"Не удалось записать {os.path.basename(self.path)}: {error}")
            return
        self._dirty = False
        self._last_flush = now


def reset_result_lists(directory=None):
    """Очищает накопленные white/black списки и возвращает имена очищенных файлов.

    Чёрный список — единственное, что НАВСЕГДА исключает игру из будущих сессий,
    поэтому у пользователя обязан быть способ его сбросить (раньше его не было
    нигде в интерфейсе, и одна разовая ошибка хоронила игру насовсем).

    directory задаётся явно, чтобы вызывающий работал с тем же каталогом, что и
    остальное хранилище: по умолчанию тут DATA_DIR, и тест с перенаправленным
    хранилищем иначе стирал бы реальные пользовательские файлы."""
    base = str(directory) if directory else get_upload_dir()
    cleared = []
    for name in ("black_list.json", "white_list.json"):
        path = os.path.join(base, name)
        try:
            if os.path.isfile(path) and load_json_list(path):
                _atomic_dump(path, [])
                cleared.append(name)
        except OSError:
            continue
    return cleared


def get_timestamp():
    """Возвращает текущее время в формате HH:MM:SS"""
    return datetime.now().strftime("%H:%M:%S")


# --- Новый строгий логгер ---
_log_lock = threading.Lock()


def log_with_time(level, appid, message):
    t = get_timestamp()
    appid_str = f"[AppID {appid}]" if appid is not None else ""
    with _log_lock:
        print(f"[{t}][{level.upper()}]{appid_str}{message}", flush=True)


class SteamBooster:
    """
    Класс для управления бустом (в разных режимах) и быстрой проверки владения играми.
    """

    def __init__(self, booster_executable: str = BOOST_WORKER_PATH):
        self.booster_executable = booster_executable
        self.booster_cwd = os.path.dirname(booster_executable)

        # Атрибуты для управления процессами буста
        self.processes: dict[str, subprocess.Popen] = {}
        self.running = False
        self.lock = threading.Lock()
        self._session_lock = threading.RLock()
        self._session_id = 0
        self._session_stop_event = threading.Event()
        self._session_done = threading.Event()
        self._session_done.set()

        self.games_done_count = 0
        self.games_done_lock = threading.Lock()
        # slot_id -> момент старта текущей задачи (под games_done_lock).
        # ETA считается из реального расписания слотов, а не из среднего времени на игру.
        self._slot_started_at = {}

        # Атрибуты для управления C#-сервером проверки владения
        self._server_proc: subprocess.Popen | None = None
        self._server_lock = threading.RLock()
        self._server_request_lock = (
            threading.Lock()
        )  # сериализует запрос+ответ к серверу
        self._server_responses = queue.Queue()
        self._server_stderr = queue.Queue()

        # Локи white/black-списков больше не нужны: синхронизацию держит сам
        # StatusListFile, который создаётся на сессию в start_boost_sliding.

    @property
    def is_busy(self) -> bool:
        return not self._session_done.is_set()

    def _begin_session(self):
        with self._session_lock:
            if not self._session_done.is_set():
                raise RuntimeError("Предыдущая сессия ещё завершается. Подождите несколько секунд.")
            self._session_id += 1
            self._session_stop_event = threading.Event()
            self._session_done.clear()
            self.running = True
            return self._session_id, self._session_stop_event

    def _finish_session(self, session_id):
        with self._session_lock:
            if session_id != self._session_id:
                return
            self.running = False
            with self.lock:
                self.processes.clear()
            self._session_done.set()

    def wait_for_stop(self, timeout=5) -> bool:
        return self._session_done.wait(timeout=max(0, timeout))

    @staticmethod
    def _normalize_range(value, minimum, maximum, fallback):
        try:
            start, end = value
            start = float(start)
            end = float(end)
        except (TypeError, ValueError, OverflowError):
            start, end = fallback
        start = max(minimum, min(maximum, start))
        end = max(minimum, min(maximum, end))
        return (start, max(start, end))

    @staticmethod
    def _normalize_appids(appids):
        normalized = []
        seen = set()
        for raw_appid in appids or []:
            value = str(raw_appid).strip()
            if not value.isdigit():
                continue
            number = int(value)
            key = str(number)
            if 0 < number <= 0xFFFFFFFF and key not in seen:
                normalized.append(key)
                seen.add(key)
        return normalized

    @staticmethod
    def _estimate_eta_seconds(slot_starts, queued_count, num_slots, task_seconds, now):
        """Остаток сессии по расписанию слотов, а не по «средней игре».

        Слот — это конвейер: он занят task_seconds на игру и берёт следующую только
        освободившись. Поэтому 18 игр в 20 слотов — это ОДНА волна на всю duration,
        а не 0.9 волны (прежняя формула len(appids)/num_slots занижала ETA на 10%
        при неполной волне и никогда не сходилась к нулю в конце).

        Занятые слоты дают остаток по факту старта, свободные — ноль. Очередь
        раскладываем жадно на самый ранний освобождающийся слот; ETA — момент,
        когда освободится последний.
        """
        finish_times = [max(0.0, start + task_seconds - now) for start in slot_starts]
        finish_times.extend([0.0] * max(0, num_slots - len(finish_times)))
        if not finish_times:
            return 0.0
        heapq.heapify(finish_times)
        for _ in range(queued_count):
            heapq.heappush(finish_times, heapq.heappop(finish_times) + task_seconds)
        return max(finish_times)

    @staticmethod
    def _notify(callback, event_type, data):
        if not callback:
            return
        try:
            callback(event_type, data)
        except Exception as error:
            log_with_time("error", None, f"Ошибка callback интерфейса: {error}")

    @staticmethod
    def _wait_process(process, stop_event):
        while process.poll() is None:
            if not stop_event.wait(0.2):
                continue
            try:
                process.terminate()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                    process.wait(timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
            break
        return process.returncode

    # --- МЕТОД 2: СКОЛЬЗЯЩИЙ БУСТ (ETA ПО РАСПИСАНИЮ СЛОТОВ) ---
    def start_boost_sliding(
        self,
        appids: list[str],
        num_slots: int,
        duration_sec: int,
        status_callback: Callable | None = None,
        unlock_achievements: bool = False,
        launch_cd_range=(1, 6),
        finish_cd_range=(1, 6),
        slot_cd_range=(5, 10),
    ):
        appids = self._normalize_appids(appids)
        self.ensure_empty_lists()
        upload_dir = get_upload_dir()
        white_list_path = os.path.join(upload_dir, "white_list.json")
        black_list_path = os.path.join(upload_dir, "black_list.json")

        if not appids:
            log_with_time("info", None, "Список игр для буста пуст. Запуск отменен.")
            self._notify(status_callback, "boost", "finished")
            return

        num_slots = max(1, min(60, int(num_slots or 1)))
        duration_sec = max(30, min(604800, int(duration_sec or 30)))
        launch_cd_range = self._normalize_range(launch_cd_range, 0, 120, (1, 6))
        finish_cd_range = self._normalize_range(finish_cd_range, 0, 120, (1, 6))
        slot_cd_range = self._normalize_range(slot_cd_range, 0, 600, (5, 10))
        session_id, stop_event = self._begin_session()

        # Списки держим в памяти на всю сессию: один чтение-старт вместо файла на игру.
        white_list = StatusListFile(white_list_path)
        black_list = StatusListFile(black_list_path)
        black_set = black_list.known_appids()
        # Имена игр читаем один раз (а не с диска на каждую завершённую игру).
        name_map = build_name_map()

        # Чёрный список отсеиваем ДО очереди: раньше воркер пропускал такие игры за доли
        # секунды, и этот «нулевой» результат втягивался в среднее время игры, обрушивая ETA.
        pending = []
        for appid in appids:
            if appid in black_set:
                log_with_time("info", appid, f"Пропуск AppID {appid} (в black_list)")
                self._notify(status_callback, appid, "skipped: black list")
            else:
                pending.append(appid)

        total_games = len(appids)
        skipped_count = total_games - len(pending)

        # Сброс состояния для нового сеанса
        with self.games_done_lock:
            self.games_done_count = skipped_count
            self._slot_started_at.clear()

        log_with_time("info", None, f"Start boost: {len(pending)} games in {num_slots} slots.")
        appid_queue = queue.Queue()
        for appid in pending:
            appid_queue.put(appid)

        # Время жизни одной задачи слота: launch_cd -> игра (duration + finish_cd) -> slot_cd.
        # duration_sec доминирует (часы против ~2 минут разброса кулдаунов), поэтому оценка
        # точна сама по себе и её не нужно «доучивать» по факту завершённых игр.
        expected_task_sec = (
            duration_sec
            + sum(launch_cd_range) / 2
            + sum(finish_cd_range) / 2
            + sum(slot_cd_range) / 2
        )

        # --- БЛОК 2: ЛОГИКА ВОРКЕРА ---
        def slot_worker(slot_id):
            while not stop_event.is_set():
                try:
                    appid = appid_queue.get_nowait()
                except queue.Empty:
                    break
                task_start_time = time.time()  # Засекаем время жизни задачи целиком

                if stop_event.is_set():
                    appid_queue.task_done()
                    break

                # Слот занят: с этого момента он вносит в ETA свой остаток задачи.
                with self.games_done_lock:
                    self._slot_started_at[slot_id] = task_start_time

                # Засчитываем игру обработанной, только если попытка реально состоялась.
                # Раньше счётчик рос в finally безусловно, и при остановке прогресс
                # скакал вверх за игры, которые ещё стояли на кулдауне запуска.
                attempted = False
                # Основная логика буста
                try:
                    # Прерываемый сон: мгновенно выходит при остановке (а не спит до 35с).
                    if stop_event.wait(random.uniform(*launch_cd_range)):
                        break

                    finish_cd = random.uniform(*finish_cd_range)
                    total_time = duration_sec + int(finish_cd)
                    proc = self._run_steambooster(
                        appid,
                        unlock_all=unlock_achievements,
                        duration_sec=total_time,
                        slot_id=slot_id,
                    )
                    with self.lock:
                        self.processes[appid] = proc
                    self._notify(status_callback, appid, "started")

                    self._wait_process(proc, stop_event)

                    # Остановлено пользователем: процесс убит принудительно — не считаем провалом
                    # и НЕ пишем в black_list (иначе игра будет пропущена в следующей сессии).
                    if stop_event.is_set():
                        self._notify(status_callback, appid, "stopped")
                        break

                    # Игра отработала свой цикл: результат есть, его можно засчитать.
                    attempted = True
                    # Обработка результата (white/black list)
                    name = name_map.get(str(appid)) or str(appid)
                    exit_code = signed_exit_code(proc.returncode)
                    if exit_code in SUCCESS_EXIT_CODES:
                        self._notify(status_callback, appid, "done")
                        # --- Добавляем в white_list.json ---
                        try:
                            white_list.add(appid, name, "OK")
                        except Exception as err:
                            log_with_time(
                                "error",
                                appid,
                                f"[WHITELIST ERROR] Не удалось записать успех для AppID {appid}: {err}",
                            )
                    else:
                        # В чёрный список — только за собственную проблему игры. Сбой среды
                        # (Steam закрыт, нет ключа в реестре, не сохранились достижения)
                        # больше не хоронит игру навсегда: она просто помечается ошибкой
                        # и будет повторена в следующей сессии.
                        if exit_code in PERMANENT_FAILURE_CODES:
                            try:
                                black_list.add(appid, name, self._failure_reason(proc))
                            except Exception as err:
                                log_with_time(
                                    "error",
                                    appid,
                                    f"[BLACKLIST ERROR] Не удалось записать ошибку для AppID {appid}: {err}",
                                )
                        self._notify(
                            status_callback, appid, f"error: {describe_exit_code(proc.returncode)}"
                        )
                    # Прерываемый межслотовый сон (а не time.sleep до 90с после остановки).
                    if stop_event.wait(random.uniform(*slot_cd_range)):
                        break
                except Exception as e:
                    # Исключение слота — это сбой окружения (не собран runtime, отказ
                    # запуска процесса), а не приговор игре, поэтому в чёрный список
                    # больше не пишем: иначе один общий сбой уносил туда всю очередь.
                    attempted = True  # попытка была и о ней сообщено — она засчитывается
                    log_with_time("error", appid, f"Слот {slot_id} AppID {appid}: {e}")
                    self._notify(status_callback, appid, f"error: {e}")
                finally:
                    # Процесс всегда убираем из словаря (успех/ошибка/исключение).
                    with self.lock:
                        self.processes.pop(appid, None)
                    # Слот освободился — ETA пересчитается по новому расписанию.
                    with self.games_done_lock:
                        self._slot_started_at.pop(slot_id, None)
                        if attempted:
                            self.games_done_count += 1
                    appid_queue.task_done()

        worker_threads = []
        for index in range(num_slots):
            worker = threading.Thread(
                target=slot_worker,
                args=(index + 1,),
                daemon=True,
                name=f"boostify-slot-{session_id}-{index + 1}",
            )
            worker_threads.append(worker)
            worker.start()

        # --- БЛОК 3: "СЕРДЦЕ" ТАЙМЕРА - МОНИТОР РАСПИСАНИЯ ---
        def monitor():
            try:
                while not stop_event.wait(1):
                    now = time.time()
                    with self.games_done_lock:
                        games_done = self.games_done_count
                        slot_starts = list(self._slot_started_at.values())

                    # Очередь считаем по счётчикам, а не через queue.qsize(): между
                    # get_nowait() и регистрацией слота qsize уже упал, и ETA
                    # проваливалась бы на целую волну на один тик.
                    tasks_finished = games_done - skipped_count
                    queued = max(0, len(pending) - tasks_finished - len(slot_starts))
                    final_eta_sec = self._estimate_eta_seconds(
                        slot_starts, queued, num_slots, expected_task_sec, now
                    )

                    # Отправляем в GUI единый, уже посчитанный результат
                    status = {
                        "games_done": games_done,
                        "games_total": total_games,
                        "final_eta_sec": int(final_eta_sec),
                    }
                    self._notify(status_callback, "progress", status)

                    if games_done >= total_games:
                        break
            except Exception as error:
                log_with_time("error", None, f"Ошибка монитора сессии: {error}")
            finally:
                stop_event.set()
                # При остановке воркеры не забирают хвост очереди. Дренируем только хвост;
                # уже взятые задачи завершат task_done() в finally своих потоков.
                while True:
                    try:
                        appid_queue.get_nowait()
                        appid_queue.task_done()
                    except queue.Empty:
                        break
                appid_queue.join()
                for worker in worker_threads:
                    worker.join(timeout=5)
                # Хвост буфера обязательно на диск: между сбросами он живёт только в памяти.
                white_list.flush()
                black_list.flush()
                self._finish_session(session_id)
                log_with_time("info", None, "Буст полностью завершен.")
                self._notify(status_callback, "boost", "finished")

        threading.Thread(target=monitor, daemon=True).start()

    def stop_boost(self):
        """Request stop. A new session remains blocked until cleanup completes."""
        with self._session_lock:
            if self._session_done.is_set():
                return False
            log_with_time("info", None, "Остановка буста...")
            self.running = False
            self._session_stop_event.set()
        with self.lock:
            processes = list(self.processes.values())
        for proc in processes:
            if proc.poll() is None:
                try:
                    proc.terminate()
                except OSError:
                    continue
        log_with_time("info", None, "Команда остановки отправлена.")
        return True

    def _run_steambooster(
        self,
        appid: str,
        unlock_all: bool = False,
        extra_args: list[str] | None = None,
        duration_sec: int | None = None,
        slot_id: int | None = None,
    ):
        """Формирует команду и запускает фоновый worker для одной игры."""
        normalized = self._normalize_appids([appid])
        if not normalized:
            raise ValueError("AppID должен быть целым числом от 1 до 4294967295.")
        if not os.path.isfile(self.booster_executable):
            raise FileNotFoundError(
                f"Не найден runtime: {self.booster_executable}. Сначала выполните сборку."
            )
        appid = normalized[0]
        cmd = [self.booster_executable, "--appid", appid]
        if unlock_all:
            cmd.append("--unlock-all")
        if duration_sec is not None:
            cmd.extend(["--exit-after", str(duration_sec)])
        if extra_args:
            cmd.extend(extra_args)

        # Логируем команду для отладки
        if slot_id is not None:
            log_with_time(
                "info",
                appid,
                f'[СЛОТ {slot_id}]Запуск: "{" ".join(cmd[1:])}", {duration_sec}c.',
            )
        else:
            log_with_time("info", appid, f"[DEBUG] Запуск команды: {' '.join(cmd[1:])}")

        process = subprocess.Popen(
            cmd,
            cwd=self.booster_cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_LOW_PRIORITY_KWARGS,
        )
        # Демон умирает вместе с GUI, даже если тот упал (см. process_group).
        process_group.track(process)
        # Буфер вывода демона наполняется ТОЛЬКО этим потоком-читателем.
        # Причина ошибки берётся из него, а не повторным чтением pipe, чтобы не было гонки.
        # deque с maxlen: нужны только последние строки, а список рос бы всю сессию (утечка).
        captured_lines = deque(maxlen=64)
        process._captured_lines = captured_lines

        def read_output():
            if process.stdout is None:
                return
            try:
                for line in iter(process.stdout.readline, ""):
                    line = line.strip()
                    if not line:
                        continue
                    captured_lines.append(line)
                    # Ошибка разблокировки ачивки
                    if "Failed to unlock achievement:" in line:
                        ach = (
                            line.split("Failed to unlock achievement:", 1)[-1]
                            .strip()
                            .rstrip(".")
                        )
                        log_with_time(
                            "error",
                            appid,
                            f"[СЛОТ {slot_id}] Не удалось разблокировать ачивку - {ach}.",
                        )
                    # Нет достижений
                    elif (
                        "No achievements found, but will emulate activity until timer expires."
                        in line
                    ):
                        log_with_time(
                            "info", appid, f"[СЛОТ {slot_id}]Достижений у игры нет."
                        )
                    # Остальные ошибки
                    elif "FATAL ERROR" in line or "ERROR" in line:
                        log_with_time("error", appid, f"[СЛОТ {slot_id}]{line}")
                    # Остальные предупреждения
                    elif "WARNING" in line:
                        log_with_time(
                            "info", appid, f"[СЛОТ {slot_id}]Достижений у игры нет."
                        )
                    # Всё остальное не выводим
            except Exception as e:
                log_with_time(
                    "error",
                    appid,
                    f"[СЛОТ {slot_id}][ERROR] Ошибка чтения вывода для AppID {appid}: {e}",
                )

        reader_thread = threading.Thread(target=read_output, daemon=True)
        reader_thread.start()
        process._reader_thread = reader_thread
        return process

    def _failure_reason(self, proc) -> str:
        """Причина провала: код выхода + последние строки вывода демона.
        Читает захваченный буфер (не pipe напрямую), чтобы не конкурировать с потоком-читателем."""
        reason = describe_exit_code(proc.returncode)
        reader = getattr(proc, "_reader_thread", None)
        if reader is not None:
            reader.join(timeout=2)
        captured = getattr(proc, "_captured_lines", None)
        if captured:
            # captured — deque(maxlen=64); он поддерживает индексацию, но НЕ срезы,
            # поэтому captured[-3:] бросал "sequence index must be integer, not 'slice'"
            # и причина провала не попадала в black_list. Материализуем в list для среза.
            tail = " | ".join(list(captured)[-3:]).strip()
            if tail:
                reason += f" | {tail}"
        return reason

    # --- МЕТОДЫ ДЛЯ БЫСТРОЙ ПРОВЕРКИ ВЛАДЕНИЯ ---

    def _ensure_server_running(self):
        """Запускает C#-сервер, если он еще не запущен."""
        with self._server_lock:
            if self._server_proc and self._server_proc.poll() is None:
                return True
            if not os.path.isfile(OWNERSHIP_WORKER_PATH):
                log_with_time("error", None, f"Не найден ownership runtime: {OWNERSHIP_WORKER_PATH}")
                return False
            log_with_time(
                "info", None, "Запуск C# сервера для проверки владения играми..."
            )
            try:
                self._server_responses = queue.Queue()
                self._server_stderr = queue.Queue()
                creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                self._server_proc = subprocess.Popen(
                    [str(OWNERSHIP_WORKER_PATH), "--server"],
                    cwd=os.path.dirname(OWNERSHIP_WORKER_PATH),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=creation_flags,
                )
                process_group.track(self._server_proc)
                self._start_server_readers()
                try:
                    line = self._read_server_protocol_line({"READY"}, timeout=10)
                    if line == "READY":
                        log_with_time("info", None, "Сервер готов к работе.")
                        return True
                except queue.Empty:
                    log_with_time(
                        "error", None, "Сервер не ответил в течение 10 секунд."
                    )
                    self._log_server_stderr()
                    self._stop_server_unlocked()
                    return False
                log_with_time("error", None, "Сервер завершился до READY.")
                self._log_server_stderr()
                self._stop_server_unlocked()
                return False
            except Exception as e:
                log_with_time(
                    "error",
                    None,
                    f"КРИТИЧЕСКАЯ ОШИБКА: Не удалось запустить C#-сервер: {e}",
                )
                self._stop_server_unlocked()
                return False

    def _start_server_readers(self):
        process = self._server_proc
        response_queue = self._server_responses
        stderr_queue = self._server_stderr

        def stdout_reader():
            if process and process.stdout:
                for line in iter(process.stdout.readline, ""):
                    line = line.strip()
                    if line:
                        response_queue.put(line)

        def stderr_reader():
            if process and process.stderr:
                for line in iter(process.stderr.readline, ""):
                    line = line.strip()
                    if line:
                        stderr_queue.put(line)

        threading.Thread(target=stdout_reader, daemon=True).start()
        threading.Thread(target=stderr_reader, daemon=True).start()

    def _read_server_protocol_line(self, expected_prefixes, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            line = self._server_responses.get(timeout=remaining)
            if any(
                line == prefix or line.startswith(prefix + " ")
                for prefix in expected_prefixes
            ):
                return line
            log_with_time("info", None, f"[SERVER] Пропущена служебная строка: {line}")
        raise queue.Empty

    def _log_server_stderr(self):
        while not self._server_stderr.empty():
            try:
                line = self._server_stderr.get_nowait()
            except queue.Empty:
                break
            log_with_time("info", None, f"[SERVER STDERR] {line}")

    def _active_server(self):
        """Снимок живого процесса сервера под локом, либо None.

        Обращаться к self._server_proc повторно нельзя: между _ensure_server_running()
        и записью в stdin другой поток мог вызвать shutdown_server(), обнулив атрибут —
        тогда self._server_proc.stdin падало с AttributeError на None и выдавалось за
        «ошибку Steam», хотя это гонка внутри приложения."""
        with self._server_lock:
            process = self._server_proc
        if process is None or process.poll() is not None or process.stdin is None:
            return None
        return process

    def check_game_owned(self, appid: int) -> bool:
        """Проверяет владение одной игрой через сервер. Блокирующий вызов."""
        try:
            appid = int(appid)
        except (TypeError, ValueError, OverflowError):
            return False
        if appid <= 0 or appid > 0xFFFFFFFF:
            return False
        if not self._ensure_server_running():
            raise RuntimeError("Не удалось запустить проверку Steam. Убедитесь, что Steam запущен, а runtime собран.")
        process = self._active_server()
        if process is None:
            raise RuntimeError("Проверка Steam остановлена. Повторите попытку.")
        try:
            with self._server_request_lock:
                process.stdin.write(f"{appid}\n")
                process.stdin.flush()
                response = self._read_server_protocol_line(
                    {"OWNED", "NOT_OWNED", "INVALID"}, timeout=10
                )
            return response == "OWNED"
        # ValueError/OSError — запись в уже закрытый другим потоком stdin.
        except (queue.Empty, BrokenPipeError, ValueError, OSError) as error:
            log_with_time(
                "error",
                appid,
                f"[ERROR] Сервер не ответил или был закрыт для AppID {appid}. Попытка перезапуска.",
            )
            self.shutdown_server()
            raise RuntimeError("Steam не ответил на проверку владения.") from error
        except Exception as e:
            log_with_time(
                "error", appid, f"[ERROR] Ошибка при проверке AppID {appid}: {e}"
            )
            self.shutdown_server()
            raise RuntimeError(f"Ошибка проверки Steam: {e}") from e

    def check_games_owned_batch(self, appids: list[str]) -> list[str]:
        """Проверяет владение списком игр через сервер. Блокирующий вызов.

        Список любой длины: он режется на пачки по SERVER_BATCH_LIMIT (столько же
        принимает C#-сервер) и результаты склеиваются. Раньше здесь стоял срез
        [:500] — всё сверх лимита молча пропадало, и игры выглядели «не купленными».
        """
        appids = self._normalize_appids(appids)
        if not appids:
            return []
        owned = []
        for offset in range(0, len(appids), SERVER_BATCH_LIMIT):
            owned.extend(self._request_owned_batch(appids[offset:offset + SERVER_BATCH_LIMIT]))
        return owned

    def _request_owned_batch(self, appids: list[str]) -> list[str]:
        """Один запрос-ответ к серверу для пачки не длиннее SERVER_BATCH_LIMIT."""
        if not self._ensure_server_running():
            raise RuntimeError("Не удалось запустить пакетную проверку Steam.")
        process = self._active_server()
        if process is None:
            raise RuntimeError("Пакетная проверка Steam остановлена. Повторите попытку.")
        try:
            with self._server_request_lock:
                command = f"BATCH {','.join(map(str, appids))}\n"
                process.stdin.write(command)
                process.stdin.flush()
                response = self._read_server_protocol_line({"OWNED"}, timeout=30)
            if response.startswith("OWNED"):
                owned_str = response.replace("OWNED", "").strip()
                if not owned_str:
                    return []
                return owned_str.split(",")
            return []
        # ValueError/OSError — запись в уже закрытый другим потоком stdin.
        except (queue.Empty, BrokenPipeError, ValueError, OSError) as error:
            log_with_time(
                "error",
                None,
                "[ERROR] Сервер не ответил или был закрыт на batch-запрос. Попытка перезапуска.",
            )
            self.shutdown_server()
            raise RuntimeError("Steam не ответил на пакетную проверку владения.") from error
        except Exception as e:
            log_with_time("error", None, f"[ERROR] Ошибка при batch-проверке: {e}")
            self.shutdown_server()
            raise RuntimeError(f"Ошибка пакетной проверки Steam: {e}") from e

    def _stop_server_unlocked(self):
        process = self._server_proc
        self._server_proc = None
        if not process or process.poll() is not None:
            return
        try:
            if process.stdin:
                process.stdin.write("exit\n")
                process.stdin.flush()
            process.wait(timeout=1)
            return
        except (OSError, BrokenPipeError, subprocess.TimeoutExpired):
            pass
        try:
            process.terminate()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def shutdown_server(self):
        """Корректно завершает работу C#-сервера."""
        with self._server_lock:
            if self._server_proc and self._server_proc.poll() is None:
                log_with_time("info", None, "Завершение работы C#-сервера...")
                self._stop_server_unlocked()
                log_with_time("info", None, "Сервер остановлен.")
            else:
                self._server_proc = None

    def ensure_empty_lists(self):
        upload_dir = get_upload_dir()
        for fname in ["black_list.json", "white_list.json"]:
            fpath = os.path.join(upload_dir, fname)
            if not os.path.isfile(fpath):
                _atomic_dump(fpath, [])


def normalize_appids(appids):
    """Публичная обёртка над отбором AppID, применяемым при старте буста.

    Нужна GUI, чтобы статистика считала games_total по тому же набору, который
    реально уйдёт в работу: раньше сеанс открывался по «сырому» списку из таблицы,
    и дубликаты или мусорные строки расходились с фактическим числом игр.
    """
    return SteamBooster._normalize_appids(appids)
