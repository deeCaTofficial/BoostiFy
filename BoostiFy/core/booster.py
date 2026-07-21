import heapq
import subprocess
import time
import threading
import os
import random
import uuid
from typing import List, Dict, Optional, Callable
from collections import deque
import queue
from datetime import datetime
import json

from BoostiFy.core.runtime_paths import BACKGROUND_WORKER, OWNERSHIP_WORKER
from BoostiFy.core.app_paths import DATA_DIR
from BoostiFy.core import process_group

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
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _atomic_dump(path, data):
    """Атомарная запись JSON: temp -> os.replace. Обрыв записи не оставит битый файл."""
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
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


def append_unique_status(list_path, lock, appid, name, status):
    with lock:
        items = load_json_list(list_path)
        if any(
            str(entry.get("appid")) == str(appid)
            for entry in items
            if isinstance(entry, dict)
        ):
            return
        items.append({"appid": str(appid), "name": name, "status": status})
        _atomic_dump(list_path, items)


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
        self.processes: Dict[str, subprocess.Popen] = {}
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
        self._server_proc: Optional[subprocess.Popen] = None
        self._server_lock = threading.RLock()
        self._server_request_lock = (
            threading.Lock()
        )  # сериализует запрос+ответ к серверу
        self._server_responses = queue.Queue()
        self._server_stderr = queue.Queue()

        self.white_list_lock = threading.Lock()
        self.black_list_lock = threading.Lock()
        self.no_achievements_lock = threading.Lock()

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

    # --- МЕТОД 1: Пакетный буст ---
    def start_boost_batch(
        self,
        appids: List[str],
        batch_size: int,
        duration_sec: int,
        status_callback: Optional[Callable] = None,
        unlock_achievements: bool = False,
    ):
        """Run batches in one guarded session."""
        appids = self._normalize_appids(appids)
        if not appids:
            self._notify(status_callback, "boost", "finished")
            return
        self.ensure_empty_lists()
        batch_size = max(1, int(batch_size or 1))
        duration_sec = max(1, int(duration_sec or 1))
        session_id, stop_event = self._begin_session()
        black_set = {
            str(entry.get("appid"))
            for entry in load_json_list(
                os.path.join(get_upload_dir(), "black_list.json")
            )
            if isinstance(entry, dict)
        }
        name_map = build_name_map()

        def boost_thread():
            try:
                total = len(appids)
                total_batches = (total + batch_size - 1) // batch_size
                session_start_time = time.time()
                log_with_time("info", None, f"Start boost: {total} games, {total_batches} batches.")
                for batch_idx, offset in enumerate(range(0, total, batch_size)):
                    if stop_event.is_set():
                        break
                    source_batch = appids[offset : offset + batch_size]
                    batch = []
                    for appid in source_batch:
                        if appid in black_set:
                            self._notify(status_callback, appid, "skipped: black list")
                        else:
                            batch.append(appid)
                    procs = []
                    log_with_time("info", None, f"--- Batch {batch_idx + 1}/{total_batches} ---")
                    for appid in batch:
                        if stop_event.is_set():
                            break
                        try:
                            proc = self._run_steambooster(
                                appid,
                                unlock_all=unlock_achievements,
                                duration_sec=duration_sec,
                            )
                            with self.lock:
                                self.processes[appid] = proc
                            procs.append((appid, proc))
                            self._notify(status_callback, appid, "started")
                        except Exception as error:
                            log_with_time("error", appid, f"Не удалось запустить игру: {error}")
                            self._notify(status_callback, appid, f"error: {error}")

                    batch_start_time = time.time()
                    while procs and not stop_event.wait(0.5):
                        if all(process.poll() is not None for _, process in procs):
                            break
                        self._emit_progress(
                            status_callback,
                            session_start_time,
                            total_batches,
                            duration_sec,
                            batch_start_time,
                        )

                    if stop_event.is_set():
                        for appid, process in procs:
                            if process.poll() is None:
                                process.terminate()
                            try:
                                process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait(timeout=2)
                            self._notify(status_callback, appid, "stopped")
                        break

                    upload_dir = get_upload_dir()
                    white_list_path = os.path.join(upload_dir, "white_list.json")
                    black_list_path = os.path.join(upload_dir, "black_list.json")
                    for appid, process in procs:
                        process.wait()
                        name = name_map.get(appid) or appid
                        with self.lock:
                            self.processes.pop(appid, None)
                        if process.returncode in (0, 42):
                            append_unique_status(
                                white_list_path, self.white_list_lock, appid, name, "OK"
                            )
                            self._notify(status_callback, appid, "done")
                        else:
                            reason = self._failure_reason(process)
                            append_unique_status(
                                black_list_path, self.black_list_lock, appid, name, reason
                            )
                            self._notify(status_callback, appid, f"error: {reason}")
            except Exception as error:
                log_with_time("error", None, f"Сбой batch-сессии: {error}")
            finally:
                self._finish_session(session_id)
                log_with_time("info", None, "Буст завершен.")
                self._notify(status_callback, "boost", "finished")

        threading.Thread(target=boost_thread, daemon=True).start()

    # --- МЕТОД 2: СКОЛЬЗЯЩИЙ БУСТ (ETA ПО РАСПИСАНИЮ СЛОТОВ) ---
    def start_boost_sliding(
        self,
        appids: List[str],
        num_slots: int,
        duration_sec: int,
        status_callback: Optional[Callable] = None,
        unlock_achievements: bool = False,
        launch_cd_range=(5, 35),
        finish_cd_range=(5, 35),
        slot_cd_range=(60, 90),
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
        launch_cd_range = self._normalize_range(launch_cd_range, 0, 120, (5, 35))
        finish_cd_range = self._normalize_range(finish_cd_range, 0, 120, (5, 35))
        slot_cd_range = self._normalize_range(slot_cd_range, 0, 600, (60, 90))
        session_id, stop_event = self._begin_session()

        # Чёрный список читаем один раз в множество (а не файл на каждую игру в воркере).
        black_set = {
            str(entry.get("appid"))
            for entry in load_json_list(black_list_path)
            if isinstance(entry, dict)
        }
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

                    # Обработка результата (white/black list)
                    name = name_map.get(str(appid)) or str(appid)
                    if proc.returncode == 0 or proc.returncode == 42:
                        self._notify(status_callback, appid, "done")
                        # --- Добавляем в white_list.json ---
                        try:
                            append_unique_status(
                                white_list_path, self.white_list_lock, appid, name, "OK"
                            )
                        except Exception as err:
                            log_with_time(
                                "error",
                                appid,
                                f"[WHITELIST ERROR] Не удалось записать успех для AppID {appid}: {err}",
                            )
                    else:
                        # --- Добавляем в black_list.json ---
                        try:
                            reason = self._failure_reason(proc)
                            append_unique_status(
                                black_list_path,
                                self.black_list_lock,
                                appid,
                                name,
                                reason,
                            )
                        except Exception as err:
                            log_with_time(
                                "error",
                                appid,
                                f"[BLACKLIST ERROR] Не удалось записать ошибку для AppID {appid}: {err}",
                            )
                        self._notify(status_callback, appid, f"error: exit code {proc.returncode}")
                    # Прерываемый межслотовый сон (а не time.sleep до 90с после остановки).
                    if stop_event.wait(random.uniform(*slot_cd_range)):
                        break
                except Exception as e:
                    log_with_time("error", appid, f"Слот {slot_id} AppID {appid}: {e}")
                    # --- Добавляем в black_list.json ---
                    try:
                        name = name_map.get(str(appid)) or str(appid)
                        append_unique_status(
                            black_list_path, self.black_list_lock, appid, name, str(e)
                        )
                    except Exception as err:
                        log_with_time(
                            "error",
                            appid,
                            f"[BLACKLIST ERROR] Не удалось записать ошибку для AppID {appid}: {err}",
                        )
                finally:
                    # Процесс всегда убираем из словаря (успех/ошибка/исключение).
                    with self.lock:
                        self.processes.pop(appid, None)
                    # Слот освободился — ETA пересчитается по новому расписанию.
                    with self.games_done_lock:
                        self._slot_started_at.pop(slot_id, None)
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
        extra_args: Optional[List[str]] = None,
        duration_sec: Optional[int] = None,
        slot_id: Optional[int] = None,
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
        reason = f"Exit code {proc.returncode}"
        reader = getattr(proc, "_reader_thread", None)
        if reader is not None:
            reader.join(timeout=2)
        captured = getattr(proc, "_captured_lines", None)
        if captured:
            tail = " | ".join(captured[-3:]).strip()
            if tail:
                reason += f" | {tail}"
        return reason

    def _emit_progress(
        self,
        status_callback,
        session_start_time,
        total_batches,
        duration_sec,
        batch_start_time,
    ):
        """Отправляет колбэк с текущим прогрессом."""
        if not status_callback:
            return
        now = time.time()
        session_elapsed = int(now - session_start_time)
        session_total = total_batches * duration_sec
        session_left = max(0, session_total - session_elapsed)
        batch_elapsed = 0
        batch_left = duration_sec
        if batch_start_time is not None:
            batch_elapsed = int(now - batch_start_time)
            batch_left = max(0, duration_sec - batch_elapsed)
        status = {
            "elapsed": session_elapsed,
            "total": session_total,
            "batch_elapsed": batch_elapsed,
            "batch_total": duration_sec,
            "session_left_sec": session_left,
            "batch_left_sec": batch_left,
        }
        self._notify(status_callback, "progress", status)

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
        try:
            with self._server_request_lock:
                self._server_proc.stdin.write(f"{appid}\n")
                self._server_proc.stdin.flush()
                response = self._read_server_protocol_line(
                    {"OWNED", "NOT_OWNED", "INVALID"}, timeout=10
                )
            return response == "OWNED"
        except (queue.Empty, BrokenPipeError):
            log_with_time(
                "error",
                appid,
                f"[ERROR] Сервер не ответил или был закрыт для AppID {appid}. Попытка перезапуска.",
            )
            self.shutdown_server()
            raise RuntimeError("Steam не ответил на проверку владения.")
        except Exception as e:
            log_with_time(
                "error", appid, f"[ERROR] Ошибка при проверке AppID {appid}: {e}"
            )
            self.shutdown_server()
            raise RuntimeError(f"Ошибка проверки Steam: {e}") from e

    def check_games_owned_batch(self, appids: List[str]) -> List[str]:
        """Проверяет владение списком игр через сервер. Блокирующий вызов."""
        appids = self._normalize_appids(appids)[:500]
        if not appids:
            return []
        if not self._ensure_server_running():
            raise RuntimeError("Не удалось запустить пакетную проверку Steam.")
        try:
            with self._server_request_lock:
                command = f"BATCH {','.join(map(str, appids))}\n"
                self._server_proc.stdin.write(command)
                self._server_proc.stdin.flush()
                response = self._read_server_protocol_line({"OWNED"}, timeout=30)
            if response.startswith("OWNED"):
                owned_str = response.replace("OWNED", "").strip()
                if not owned_str:
                    return []
                return owned_str.split(",")
            else:
                return []
        except (queue.Empty, BrokenPipeError):
            log_with_time(
                "error",
                None,
                "[ERROR] Сервер не ответил или был закрыт на batch-запрос. Попытка перезапуска.",
            )
            self.shutdown_server()
            raise RuntimeError("Steam не ответил на пакетную проверку владения.")
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
