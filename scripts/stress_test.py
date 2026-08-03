"""Нагрузочные проверки перед релизом.

Дополняют smoke_test (целостность сборки) и functional_qa (сценарии интерфейса):
здесь проверяется поведение под конкуренцией, на повреждённых данных и на полном
цикле буста с реальными процессами. Каждый блок закрывает дефект, который уже
проявлялся на практике, поэтому объёмы подобраны так, чтобы прогон укладывался
в CI, но нагрузка оставалась осмысленной.
"""

import json
import os
import random
import sys
import tempfile
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Вывод держим в UTF-8: на CI stdout по умолчанию cp1252, и любой не-ASCII символ
# (например, имя игры в тексте ошибки) обрушивал бы прогон UnicodeEncodeError.
for stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[OK] {message}")


# --------------------------------------------------------------------------- #
def test_result_list_concurrency():
    """Списки результатов пишут все слоты сразу — дубликатов быть не должно."""
    from BoostiFy.core.booster import StatusListFile

    with tempfile.TemporaryDirectory(prefix="boostify-stress-") as tmp:
        path = Path(tmp) / "black_list.json"
        writer = StatusListFile(path, flush_interval=0.01)
        accepted = []
        lock = threading.Lock()

        def worker(base):
            local = 0
            for index in range(100):
                # Каждый третий AppID намеренно общий для всех потоков.
                appid = (base * 100 + index) if index % 3 else (index % 20)
                if writer.add(appid, f"Game {appid}", "Exit code 3"):
                    local += 1
            with lock:
                accepted.append(local)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(20)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        writer.flush()

        stored = [entry["appid"] for entry in json.loads(path.read_text(encoding="utf-8"))]
        check(len(stored) == len(set(stored)), "concurrent writes never create duplicates")
        check(sum(accepted) == len(stored), "accepted entries match the file contents")
        check(writer.known_appids() == set(stored), "in-memory index matches the file")


def test_writes_survive_concurrent_readers():
    """Windows не даёт подменить файл, пока его кто-то открыл (антивирус, индексатор).

    Без повторов в replace_with_retry терялось подавляющее большинство сохранений.
    """
    from BoostiFy.GUI.core import game_storage

    with tempfile.TemporaryDirectory(prefix="boostify-stress-") as tmp:
        game_storage.configure_storage(tmp)
        payload = [
            {"appid": str(1000 + i), "name": f"Игра {i}", "status": "Ожидание"}
            for i in range(500)
        ]
        failures, torn = [], []
        stop = threading.Event()

        def reader():
            target = Path(tmp) / "user_games.json"
            while not stop.is_set():
                try:
                    if not isinstance(json.loads(target.read_text(encoding="utf-8-sig")), list):
                        torn.append("не список")
                except json.JSONDecodeError as error:
                    torn.append(str(error))
                except OSError:
                    pass  # файл занят подменой — это не порча
                time.sleep(0.002)

        def writer():
            for _ in range(15):
                try:
                    game_storage.save_games(payload)
                except Exception as error:  # noqa: BLE001 — фиксируем любой отказ записи
                    failures.append(f"{type(error).__name__}: {error}")

        readers = [threading.Thread(target=reader, daemon=True) for _ in range(2)]
        for thread in readers:
            thread.start()
        writers = [threading.Thread(target=writer) for _ in range(4)]
        for thread in writers:
            thread.start()
        for thread in writers:
            thread.join()
        stop.set()
        for thread in readers:
            thread.join(timeout=2)

        check(not torn, "readers never observe a half-written file")
        check(not failures, f"no save was lost ({len(failures)} failures)")
        check(not list(Path(tmp).glob("*.tmp")), "temporary files never linger on disk")


def test_corrupted_files_do_not_break_startup():
    """Любой мусор в пользовательских файлах должен деградировать до значений по умолчанию."""
    from BoostiFy.core.booster import StatusListFile, load_json_list
    from BoostiFy.GUI.core import game_storage
    from BoostiFy.GUI.core.statistics_storage import load_statistics

    payloads = ['{"broken', "", "null", "12345", '{"a":1}', "[1,2,3]", '["строка"]', "\x00\xff"]
    with tempfile.TemporaryDirectory(prefix="boostify-stress-") as tmp:
        game_storage.configure_storage(tmp)
        for index, payload in enumerate(payloads):
            for name in ("user_games.json", "config.json", "statistics.json", "black_list.json"):
                (Path(tmp) / name).write_text(payload, encoding="utf-8", errors="ignore")
            games = game_storage.load_games()
            config = game_storage.load_config()
            stats = load_statistics()
            entries = load_json_list(str(Path(tmp) / "black_list.json"))
            StatusListFile(Path(tmp) / "black_list.json", flush_interval=3600)
            check(
                isinstance(games, list)
                and isinstance(entries, list)
                and config == game_storage.normalize_config(config)
                and stats["total_sessions"] >= 0,
                f"corrupted payload #{index} never breaks loading",
            )


def test_statistics_invariants_hold():
    """Счётчики статистики не должны разъезжаться на длинной серии сессий."""
    from BoostiFy.GUI.core import game_storage
    from BoostiFy.GUI.core.statistics_storage import (
        finish_statistics_session,
        load_statistics,
        start_statistics_session,
    )

    with tempfile.TemporaryDirectory(prefix="boostify-stress-") as tmp:
        game_storage.configure_storage(tmp)
        random.seed(11)
        broken = []
        for index in range(60):
            session = start_statistics_session(random.randint(0, 50))
            if random.random() < 0.15:
                continue  # брошенная сессия: следующая обязана её подобрать
            finish_statistics_session(
                session,
                successful_games=random.randint(0, 60),
                failed_games=random.randint(0, 60),
                skipped_games=random.randint(0, 60),
                stopped=random.random() < 0.3,
                interrupted=random.random() < 0.1,
            )
            stats = load_statistics()
            if not (
                stats["completed_sessions"] + stats["stopped_sessions"] <= stats["total_sessions"]
                and stats["interrupted_sessions"] <= stats["stopped_sessions"]
                and len(stats["recent_sessions"]) <= 8
                and stats["total_runtime_seconds"] >= 0
            ):
                broken.append(index)
        check(not broken, "statistics counters stay consistent across 60 sessions")


# --------------------------------------------------------------------------- #
def _write_worker_stub(directory: Path) -> Path:
    """Заглушка воркера: возвращает код из переменной окружения FAKE_EXIT_CODE."""
    stub = directory / "worker.bat"
    stub.write_text(
        "@echo off\r\n"
        "echo [INFO] stub worker %*\r\n"
        "exit /b %FAKE_EXIT_CODE%\r\n",
        encoding="ascii",
    )
    return stub


def _finish_callback(event_flag):
    """Колбэк «сессия завершилась» с явной привязкой события (иначе лямбда в цикле
    захватывала бы переменную по ссылке)."""
    def callback(event, data):
        if event == "boost" and data == "finished":
            event_flag.set()
    return callback


def _run_session(booster, stub_appids, exit_code, slots):
    os.environ["FAKE_EXIT_CODE"] = str(exit_code)
    statuses, progress, finished = {}, [], threading.Event()

    def callback(event, data):
        if event == "progress":
            progress.append(data)
        elif event == "boost" and data == "finished":
            finished.set()
        else:
            statuses[str(event)] = str(data)

    booster.start_boost_sliding(
        stub_appids, slots, 30, callback,
        unlock_achievements=False,
        launch_cd_range=(0, 0), finish_cd_range=(0, 0), slot_cd_range=(0, 0),
    )
    check(finished.wait(timeout=180), "session finishes within the allotted time")
    return statuses, progress


def test_boost_lifecycle_with_real_processes():
    """Полный цикл буста: подменён только исполняемый файл воркера."""
    if os.name != "nt":
        print("[SKIP] boost lifecycle with real processes runs on Windows only")
        return

    from BoostiFy.core import booster as booster_module
    from BoostiFy.core.booster import SteamBooster

    original_upload_dir = booster_module.get_upload_dir
    with tempfile.TemporaryDirectory(prefix="boostify-stress-") as tmp:
        root = Path(tmp)
        booster_module.get_upload_dir = lambda: str(root)
        try:
            stub = _write_worker_stub(root)
            appids = [str(i) for i in range(1, 61)]
            (root / "user_games.json").write_text(
                json.dumps([{"appid": a, "name": f"Игра {a}", "status": "Ожидание"} for a in appids]),
                encoding="utf-8",
            )

            statuses, progress = _run_session(SteamBooster(str(stub)), appids, 0, slots=15)
            check(set(statuses.values()) == {"done"}, "successful run marks every game as done")
            check(len(json.loads((root / "white_list.json").read_text(encoding="utf-8"))) == len(appids),
                  "successful games land in the white list")
            check(json.loads((root / "black_list.json").read_text(encoding="utf-8")) == [],
                  "successful run never fills the blacklist")
            check(progress[-1]["games_done"] == len(appids), "progress reaches the full game count")

            statuses, _ = _run_session(SteamBooster(str(stub)), appids, 3, slots=15)
            check(len(json.loads((root / "black_list.json").read_text(encoding="utf-8"))) == len(appids),
                  "game-specific failure (code 3) is blacklisted")
            check(all("недоступна" in value for value in statuses.values()),
                  "failure reason is explained in plain language")

            statuses, _ = _run_session(SteamBooster(str(stub)), appids, 0, slots=15)
            check(all(value == "skipped: black list" for value in statuses.values()),
                  "blacklisted games are skipped in the next session")

            for code in (2, 101):
                (root / "black_list.json").write_text("[]", encoding="utf-8")
                statuses, _ = _run_session(SteamBooster(str(stub)), appids[:20], code, slots=10)
                check(json.loads((root / "black_list.json").read_text(encoding="utf-8")) == [],
                      f"transient failure (code {code}) is not blacklisted")
                check(all(value.startswith("error:") for value in statuses.values()),
                      f"transient failure (code {code}) is reported as an error")
        finally:
            booster_module.get_upload_dir = original_upload_dir


def test_stop_and_restart_cycles():
    """Быстрые остановки не должны оставлять зависшую сессию или потоки."""
    if os.name != "nt":
        print("[SKIP] stop/restart cycles run on Windows only")
        return

    from BoostiFy.core import booster as booster_module
    from BoostiFy.core.booster import SteamBooster

    original_upload_dir = booster_module.get_upload_dir
    baseline_threads = threading.active_count()
    with tempfile.TemporaryDirectory(prefix="boostify-stress-") as tmp:
        root = Path(tmp)
        booster_module.get_upload_dir = lambda: str(root)
        try:
            stub = _write_worker_stub(root)
            os.environ["FAKE_EXIT_CODE"] = "0"
            booster = SteamBooster(str(stub))
            for _ in range(5):
                finished = threading.Event()
                booster.start_boost_sliding(
                    [str(i) for i in range(1, 61)], 20, 30,
                    _finish_callback(finished),
                    launch_cd_range=(0, 1), finish_cd_range=(0, 0), slot_cd_range=(0, 1),
                )
                time.sleep(0.2)
                booster.stop_boost()
                check(finished.wait(timeout=60), "stopped session shuts down without hanging")
            check(not booster.is_busy, "state is clean after a series of stops")
            check(json.loads((root / "black_list.json").read_text(encoding="utf-8")) == [],
                  "a user stop never blacklists games")

            finished = threading.Event()
            booster.start_boost_sliding(
                [str(i) for i in range(1, 21)], 5, 30,
                _finish_callback(finished),
                launch_cd_range=(0, 1), finish_cd_range=(0, 0), slot_cd_range=(0, 1),
            )
            try:
                booster.start_boost_sliding(["1"], 1, 30, None)
                check(False, "a second start is rejected")
            except RuntimeError:
                check(True, "a second start is rejected with a clear error")
            booster.stop_boost()
            finished.wait(timeout=60)
        finally:
            booster_module.get_upload_dir = original_upload_dir

    time.sleep(1.0)
    check(threading.active_count() - baseline_threads <= 2, "threads do not leak between sessions")


# --------------------------------------------------------------------------- #
def test_interface_survives_random_actions():
    """Хаотичные нажатия не должны ломать интерфейс или выводить настройки из границ."""
    from PyQt6.QtWidgets import QApplication, QDialog

    from BoostiFy.GUI.core import game_storage
    from BoostiFy.GUI.widgets import toast

    toast.InfoDialog.exec = lambda self: QDialog.DialogCode.Accepted
    toast.CustomConfirmDialog.exec = lambda self: QDialog.DialogCode.Accepted

    with tempfile.TemporaryDirectory(prefix="boostify-stress-") as tmp:
        game_storage.configure_storage(tmp)
        game_storage.ensure_default_config()

        app = QApplication.instance() or QApplication(sys.argv)
        import BoostiFy.GUI.main_window as main_window_module

        main_window_module.runtime_is_ready = lambda: True
        main_window_module.missing_runtime_files = list
        window = main_window_module.MainWindow()
        screen, settings = window.main_screen, window.settings_screen

        random.seed(5)
        pairs = list(settings._CD_BOUNDS)
        for step in range(800):
            action = random.randrange(8)
            if action == 0:
                settings._adjust_cd(
                    f"{random.choice(pairs)}_{random.choice(('from', 'to'))}", random.choice((-1, 1))
                )
            elif action == 1:
                (settings._pending_increment_games if random.random() < 0.5
                 else settings._pending_decrement_games)()
            elif action == 2:
                (settings._pending_increment_time if random.random() < 0.5
                 else settings._pending_decrement_time)()
            elif action == 3:
                (settings._pending_increment_table_rows if random.random() < 0.5
                 else settings._pending_decrement_table_rows)()
                screen.visible_rows = settings._pending_table_rows
                screen.apply_row_density()
            elif action == 4:
                settings._set_section(random.randrange(5))
            elif action == 5:
                screen.filter_text = random.choice(["", "иг", "10", "zzz"])
                screen.update_game_list()
            elif action == 6:
                screen.add_game(random.randint(1, 200), f"Игра {step}")
            else:
                screen._sort_by(random.choice(["num", "appid", "name", "status"]))
            if step % 200 == 0:
                app.processEvents()
        app.processEvents()

        config = game_storage.load_config()
        check(
            all(
                low <= config[f"{pair}_cd_{edge}"] <= high
                for pair, bounds in game_storage.CD_BOUNDS.items()
                for edge, (low, high) in zip(("from", "to"), bounds, strict=True)
            ),
            "cooldowns stay within the declared bounds",
        )
        check(
            all(
                config[f"{pair}_cd_to"] - config[f"{pair}_cd_from"] >= game_storage.MIN_CD_SPREAD
                for pair in game_storage.CD_BOUNDS
            ),
            "the minimum cooldown spread is preserved",
        )
        check(game_storage.normalize_config(config) == config, "the config on disk is canonical")

        heights = {}
        for rows in range(5, 21):
            screen.visible_rows = rows
            screen.apply_row_density()
            heights[rows] = screen.game_table.verticalHeader().defaultSectionSize()
        check(all(heights[r] >= heights[r + 1] for r in range(5, 20)),
              "table density changes monotonically")
        check(all(height >= screen.min_row_height for height in heights.values()),
              "a table row never collapses below the minimum")
        window.close()


def test_late_callbacks_survive_window_teardown():
    """Фоновые задачи завершаются уже после закрытия окна.

    Проверка владения блокируется до 10 секунд, поэтому её колбэки регулярно
    приходят, когда виджеты уже уничтожены. Без защиты выход из программы падал
    с «wrapped C/C++ object of type QPushButton has been deleted».
    """
    from PyQt6 import sip
    from PyQt6.QtWidgets import QApplication, QDialog

    from BoostiFy.GUI.core import game_storage
    from BoostiFy.GUI.widgets import toast

    toast.InfoDialog.exec = lambda self: QDialog.DialogCode.Accepted
    toast.CustomConfirmDialog.exec = lambda self: QDialog.DialogCode.Accepted

    with tempfile.TemporaryDirectory(prefix="boostify-stress-") as tmp:
        game_storage.configure_storage(tmp)
        game_storage.ensure_default_config()
        app = QApplication.instance() or QApplication(sys.argv)
        import BoostiFy.GUI.main_window as main_window_module

        main_window_module.runtime_is_ready = lambda: True
        main_window_module.missing_runtime_files = list

        # Корень проблемы: задача из пула отчитывается уже после уничтожения своего
        # QObject. Раньше исключение всплывало из QRunnable.run прямо в рабочем потоке.
        from BoostiFy.GUI.core.async_tasks import BackgroundTask

        task = BackgroundTask(lambda cancel_event, report: report("промежуточный результат"))
        sip.delete(task.signals)
        task.run()
        check(True, "background task survives its destroyed signals")

        window = main_window_module.MainWindow()
        screen, settings = window.main_screen, window.settings_screen
        settings._set_background_busy(True)
        tracked_buttons = list(settings._buttons_disabled_for_task)

        window.close()  # closeEvent обязан погасить фоновые задачи обоих экранов
        check(screen._closing and settings._closing,
              "closing the window marks both screens as closing")

        # Точный сценарий из отчёта: кнопка уже уничтожена, а колбэк ещё придёт.
        sip.delete(tracked_buttons[0])
        settings._buttons_disabled_for_task = tracked_buttons
        settings._closing = False  # худший случай: флаг не выставлен, а виджет мёртв
        settings._set_background_busy(False)
        check(True, "button restore survives a destroyed widget")
        settings._closing = True

        late_calls = (
            ("add-game task finished", lambda: screen._on_add_finished()),
            ("game resolved", lambda: screen._on_game_resolved({"appid": "570", "name": "Dota 2"})),
            ("add rejected", lambda: screen._reject_add("поздний отказ")),
            ("game status updated", lambda: screen._set_game_status_slot("570", "done")),
            ("progress updated", lambda: screen._update_progress_bar_slot(
                {"games_done": 1, "games_total": 2, "final_eta_sec": 5})),
            ("table repainted", lambda: screen._force_table_update_slot()),
            ("progress reset", lambda: screen.reset_progress_bar()),
            ("bulk add finished", lambda: settings._on_add_all_finished()),
            ("bulk add reported progress", lambda: settings._on_add_all_progress(
                {"checked": 1, "total": 2, "eta": 1})),
            ("bulk add failed", lambda: settings._on_add_all_error("поздняя ошибка")),
        )
        for description, call in late_calls:
            call()
            check(True, f"late callback is safe: {description}")
        app.processEvents()


def test_dialog_text_always_fits():
    """Текст диалогов не должен вылезать за края окна.

    Высоту меряет сам QLabel и только после полировки стилей: QFontMetrics переносит
    текст иначе, чем виджет, а `padding` из таблицы стилей диалога каскадом сужает
    подпись. Из-за этого сообщение обещало 48px, занимало 104px и обрезалось.
    """
    from PyQt6.QtWidgets import QApplication

    from BoostiFy.GUI.widgets.toast import CustomConfirmDialog, InfoDialog

    # Ссылку на приложение держим в переменной: без неё объект собирает сборщик
    # мусора и процесс падает при разрушении Qt.
    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None

    confirmations = (
        ("Очистить кэш каталога Steam и накопленные результаты?\n"
         "Игры из чёрного списка снова станут доступны для буста", "Очистить", "Отмена"),
        ("Разблокировка достижений изменяет данные Steam и может быть необратимой. Продолжить?",
         "Продолжить", "Отмена"),
        ("Вы действительно хотите добавить все игры, которыми вы владеете? \n"
         "Это может занять несколько минут!", "Да", "Нет"),
        ("Удалить все игры из таблицы? Это действие нельзя отменить.", "Удалить", "Отмена"),
        ("Удалить конфиг config_20260803_120000_123456.json?", "Удалить", "Отмена"),
    )
    for index, (message, yes_text, no_text) in enumerate(confirmations, 1):
        dialog = CustomConfirmDialog(None, message, yes_text, no_text)
        label = dialog.label.geometry()
        needed = dialog.label.heightForWidth(label.width())
        check(needed <= label.height() and label.bottom() <= dialog.btn_yes.geometry().top(),
              f"text fits the confirm dialog #{index}")

    notices = (
        "Список игр пуст. Сначала добавьте хотя бы одну игру.",
        "Steam runtime не готов. Отсутствуют: Boostify.Worker.exe.\n\n"
        "Выполните: python BoostiFy/runtime/build.py",
        "Нужно точное название. Возможно, вы искали: Counter-Strike 2 (AppID 730), "
        "Counter-Strike (AppID 10)",
    )
    for index, message in enumerate(notices, 1):
        dialog = InfoDialog(None, message)
        label = dialog.label.geometry()
        needed = dialog.label.heightForWidth(label.width())
        check(needed <= label.height() and label.bottom() <= dialog.btn_ok.geometry().top(),
              f"text fits the notice dialog #{index}")


def test_ownership_requests_race_with_shutdown():
    """Остановка сервера во время запроса обязана давать понятную ошибку, а не падение."""
    from BoostiFy.core.booster import SteamBooster

    booster = SteamBooster("missing.exe")
    booster._ensure_server_running = lambda: True
    unexpected = []

    class ClosedPipe:
        def __init__(self):
            self.stdin = self

        def poll(self):
            return None

        def write(self, _):
            raise ValueError("I/O operation on closed file")

        def flush(self):
            pass

    def churn():
        for _ in range(150):
            booster._server_proc = ClosedPipe()
            booster._server_proc = None

    def ask():
        for _ in range(150):
            try:
                booster.check_game_owned(570)
            except RuntimeError:
                pass
            except Exception as error:  # noqa: BLE001 — ловим именно неожиданное
                unexpected.append(f"{type(error).__name__}: {error}")

    threads = [threading.Thread(target=churn)] + [threading.Thread(target=ask) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    check(not unexpected, "racing the server shutdown raises nothing unexpected")


def main():
    started = time.time()
    test_result_list_concurrency()
    test_writes_survive_concurrent_readers()
    test_corrupted_files_do_not_break_startup()
    test_statistics_invariants_hold()
    test_boost_lifecycle_with_real_processes()
    test_stop_and_restart_cycles()
    test_interface_survives_random_actions()
    test_late_callbacks_survive_window_teardown()
    test_dialog_text_always_fits()
    test_ownership_requests_race_with_shutdown()
    print(f"\n[OK] Stress checks passed in {time.time() - started:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
