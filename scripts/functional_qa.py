import json
import os
import sys
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# No live GitHub request from a test run: it would be flaky, count against the
# API rate limit and write update state into the real user data directory.
os.environ["BOOSTIFY_NO_UPDATE_CHECK"] = "1"

# GitHub Windows runners may expose cp1252 to Python. Russian diagnostics from a
# Qt callback must never raise UnicodeEncodeError and abort the whole GUI test.
for stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[OK] {message}")


def wait_until(app, condition, message, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        app.processEvents()
        if condition():
            check(True, message)
            return
        time.sleep(0.01)
    raise AssertionError(f"Timed out waiting for: {message}")


class FakeLookup:
    def __init__(self, *_args, **_kwargs):
        self.apps = [
            {"appid": 10, "name": "Counter-Strike", "status": "OK"},
            {"appid": 20, "name": "Team Fortress Classic", "status": "OK"},
            {"appid": 570, "name": "Dota 2", "status": "OK"},
        ]

    def ensure_loaded(self):
        return True

    def find_appid(self, name):
        query = " ".join(str(name).strip().lower().split())
        for app in self.apps:
            app_name = " ".join(app["name"].lower().split())
            if app_name == query:
                return app["appid"]
        for app in self.apps:
            if query in app["name"].lower():
                return app["appid"]
        return None

    def find_exact_appid(self, name):
        query = " ".join(str(name).strip().lower().split())
        for app in self.apps:
            if " ".join(app["name"].lower().split()) == query:
                return app["appid"]
        return None

    def get_name(self, appid):
        for app in self.apps:
            if str(app["appid"]) == str(appid):
                return app["name"]
        return None

    def find_similar(self, name, limit=5):
        query = str(name).strip().lower()
        return [app for app in self.apps if query in app["name"].lower()][:limit]

    def _rebuild_index(self):
        return None


class FakeBooster:
    owned = {"10", "20", "570"}

    def __init__(self, *_args, **_kwargs):
        self.start_calls = []
        self.stopped = False
        self.shutdown_called = 0
        self.is_busy = False

    def check_game_owned(self, appid):
        return str(appid) in self.owned

    def check_games_owned_batch(self, appids):
        return [str(appid) for appid in appids if str(appid) in self.owned]

    def start_boost_sliding(self, appids, num_slots, duration_sec, callback, unlock_achievements=False, **kwargs):
        self.start_calls.append(
            {
                "appids": list(appids),
                "num_slots": num_slots,
                "duration_sec": duration_sec,
                "unlock_achievements": unlock_achievements,
                "kwargs": kwargs,
            }
        )
        # Отдаём КОДЫ ПРОТОКОЛА, как настоящий SteamBooster, а не готовые подписи:
        # иначе прогон минует _display_status и не заметит рассинхрон переводов.
        for appid in appids:
            callback(appid, "started")
        callback(
            "progress",
            {
                "games_done": len(appids),
                "games_total": len(appids),
                "final_eta_sec": 0,
            },
        )
        for appid in appids:
            callback(appid, "done")
        callback("boost", "finished")

    def stop_boost(self):
        self.stopped = True
        return False

    def shutdown_server(self):
        self.shutdown_called += 1

    def wait_for_stop(self, timeout=5):
        return True


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "applist": {
                "apps": [
                    {"appid": 10, "name": "Counter-Strike"},
                    {"appid": 570, "name": "Dota 2"},
                    {"appid": "20", "name": "Team Fortress Classic"},
                    {"appid": 999999, "name": "Not Owned"},
                    {"broken": True},
                ]
            }
        }


def configure_isolated_storage(temp_dir):
    from BoostiFy.core import app_paths
    from BoostiFy.GUI.core import game_storage

    game_storage.configure_storage(temp_dir)
    game_storage.ensure_default_config()
    # Not everything goes through game_storage: the update checker keeps its state
    # next to DATA_DIR, so redirect that root too or the run writes into the real
    # %LOCALAPPDATA%\BoostiFy.
    app_paths.DATA_DIR = Path(temp_dir)
    return game_storage


def patch_dialogs():
    from PyQt6.QtWidgets import QDialog

    from BoostiFy.GUI.widgets import toast

    toast.InfoDialog.exec = lambda self: QDialog.DialogCode.Accepted
    toast.CustomConfirmDialog.exec = lambda self: QDialog.DialogCode.Accepted


def check_update_notification(app, window, main_window_module, temp_dir):
    """Update prompt: opens GitHub on accept, stays quiet once skipped.

    The network layer is covered by unit tests; here the GitHub answer is stubbed so
    the run stays offline and only the window wiring is exercised.
    """
    from PyQt6.QtCore import QThreadPool
    from PyQt6.QtWidgets import QDialog

    from BoostiFy.core import updates

    original_check = main_window_module.check_for_update
    original_dialog = main_window_module.UpdateDialog
    original_open = main_window_module.QDesktopServices.openUrl
    state_file = temp_dir / "update_state.json"
    opened = []
    shown = []
    answer = {"value": QDialog.DialogCode.Accepted}

    def fake_check():
        skipped = updates.load_skipped_version()
        if skipped == "v9.9.9":
            return None
        return updates.UpdateInfo(version="v9.9.9", url=updates.RELEASES_PAGE, current="1.0.0")

    class FakeDialog:
        def __init__(self, parent, new_version, current_version):
            shown.append((new_version, current_version))

        def exec(self):
            return answer["value"]

    def run_check():
        window.check_for_update_async()
        QThreadPool.globalInstance().waitForDone(10000)
        app.processEvents()
        app.processEvents()

    main_window_module.check_for_update = fake_check
    main_window_module.UpdateDialog = FakeDialog
    main_window_module.QDesktopServices.openUrl = lambda url: opened.append(url.toString())
    try:
        run_check()
        check(shown == [("v9.9.9", "1.0.0")], "newer release on GitHub raises the update prompt")
        check(opened == [updates.RELEASES_PAGE], "accepting the prompt opens the release page")
        check(not state_file.exists(), "downloading does not mark the version as skipped")

        answer["value"] = QDialog.DialogCode.Rejected
        shown.clear()
        run_check()
        check(len(shown) == 1, "prompt reappears while the version was not answered")
        check(
            json.loads(state_file.read_text(encoding="utf-8")).get("skipped_version") == "v9.9.9",
            "skipping remembers the exact version",
        )

        shown.clear()
        run_check()
        check(shown == [], "skipped version is never offered again")

        def failing_check():
            raise OSError("network unreachable")

        main_window_module.check_for_update = failing_check
        shown.clear()
        run_check()
        check(shown == [], "unreachable GitHub raises no dialog")
        check(window._update_task is None, "a failed check releases the task slot")
        check(not window._closing, "a failed check does not shut the window down")

        main_window_module.check_for_update = fake_check
        window._closing = True
        shown.clear()
        run_check()
        check(shown == [], "no update prompt once the window is closing")
        window._closing = False
    finally:
        main_window_module.check_for_update = original_check
        main_window_module.UpdateDialog = original_dialog
        main_window_module.QDesktopServices.openUrl = original_open


def main():
    with tempfile.TemporaryDirectory(prefix="boostify-functional-qa-") as temp_dir:
        game_storage = configure_isolated_storage(temp_dir)
        patch_dialogs()

        from PyQt6.QtCore import QEvent, QItemSelectionModel, Qt
        from PyQt6.QtGui import QGuiApplication, QKeyEvent
        from PyQt6.QtWidgets import QApplication

        import BoostiFy.GUI.main_window as main_window_module
        import BoostiFy.GUI.screens.settings_screen as settings_module

        main_window_module.runtime_is_ready = lambda: True
        main_window_module.missing_runtime_files = list
        MainWindow = main_window_module.MainWindow

        app = QApplication.instance() or QApplication(sys.argv)
        window = MainWindow()
        main_screen = window.main_screen
        settings = window.settings_screen

        fake_booster = FakeBooster()
        main_screen.app_lookup = FakeLookup()
        main_screen.booster = fake_booster
        window.booster = fake_booster

        check(window.stacked_widget.count() == 2, "main window opens with main and settings screens")
        check(main_screen.progress_bar.format() == "Добавьте игры для буста.", "empty table shows useful ETA text")

        main_screen.try_add_game("")
        check(len(main_screen.games) == 0, "empty input is rejected")
        main_screen.try_add_game("10")
        wait_until(app, lambda: not main_screen._add_in_progress, "numeric AppID check completes")
        check([g["appid"] for g in main_screen.games] == ["10"], "numeric owned AppID can be added")
        main_screen.try_add_game("10")
        wait_until(app, lambda: not main_screen._add_in_progress, "duplicate AppID check completes")
        check(len(main_screen.games) == 1, "duplicate AppID is rejected")
        main_screen.try_add_game("999999")
        wait_until(app, lambda: not main_screen._add_in_progress, "not-owned AppID check completes")
        check(len(main_screen.games) == 1, "not-owned AppID is rejected")
        fake_booster.owned.remove("570")
        main_screen.try_add_game("Dota 2")
        wait_until(app, lambda: not main_screen._add_in_progress, "not-owned name check completes")
        check({g["appid"] for g in main_screen.games} == {"10"}, "game names cannot bypass ownership checks")
        fake_booster.owned.add("570")
        main_screen.try_add_game("Dota 2")
        wait_until(app, lambda: not main_screen._add_in_progress, "name ownership check completes")
        check({g["appid"] for g in main_screen.games} == {"10", "570"}, "exact game name lookup can add a game")
        main_screen.add_game(20, "Team Fortress Classic")
        check(all(isinstance(g["appid"], str) for g in main_screen.games), "table stores AppIDs as strings")

        main_screen.filter_text = "dota"
        main_screen.update_game_list()
        selection = main_screen.game_table.selectionModel()
        selection.select(
            main_screen.game_table_model.index(0, 0),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows,
        )
        main_screen.remove_selected_game()
        check({g["appid"] for g in main_screen.games} == {"10", "20"}, "deleting a filtered row removes the right source item")

        main_screen.filter_text = "counter"
        main_screen.update_game_list()
        ctrl_a = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        main_screen.eventFilter(main_screen.game_table, ctrl_a)
        check(main_screen.selected_rows == {0}, "Ctrl+A selects only visible filtered rows")
        main_screen.selected_rows.clear()
        main_screen.filter_text = ""
        main_screen.update_game_list()

        window.fast_paste_enabled = True
        QGuiApplication.clipboard().setText("Dota 2")
        ctrl_v = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_V, Qt.KeyboardModifier.ControlModifier)
        main_screen.eventFilter(main_screen.game_table, ctrl_v)
        wait_until(app, lambda: not main_screen._add_in_progress, "fast-paste ownership check completes")
        check({g["appid"] for g in main_screen.games} == {"10", "20", "570"}, "fast paste adds clipboard AppID/name")

        window.show_settings()
        check(window.stacked_widget.currentIndex() == 1, "settings screen opens")
        check(
            settings.btn_clear_cache.x() == settings.btn_cfg_save.x()
            and settings.btn_clear_cache.size() == settings.btn_cfg_save.size()
            and settings.btn_fast_copy_toggle.x() == settings.btn_cfg_load.x()
            and settings.btn_fast_copy_toggle.size() == settings.btn_cfg_load.size(),
            "general settings button columns align",
        )
        cooldown_rows = (
            (
                settings.btn_cd1_from_minus,
                settings.cd1_from_label,
                settings.btn_cd1_from_plus,
                settings.cd1_title_label,
                settings.btn_cd1_to_minus,
                settings.cd1_to_label,
                settings.btn_cd1_to_plus,
            ),
            (
                settings.btn_cd2_from_minus,
                settings.cd2_from_label,
                settings.btn_cd2_from_plus,
                settings.cd2_title_label,
                settings.btn_cd2_to_minus,
                settings.cd2_to_label,
                settings.btn_cd2_to_plus,
            ),
            (
                settings.btn_cd3_from_minus,
                settings.cd3_from_label,
                settings.btn_cd3_from_plus,
                settings.cd3_title_label,
                settings.btn_cd3_to_minus,
                settings.cd3_to_label,
                settings.btn_cd3_to_plus,
            ),
        )
        check(
            all(
                all(
                    right.x() - (left.x() + left.width()) == 10
                    for left, right in zip(row[:-1], row[1:], strict=True)
                )
                for row in cooldown_rows
            ),
            "professional cooldown controls use uniform spacing",
        )
        settings._set_section(4)
        app.processEvents()
        check(
            settings.right_stack.currentIndex() == 4 and settings.btn_left_stats.isChecked(),
            "statistics navigation opens and highlights the dashboard",
        )
        check(
            settings.statistics_panel.snapshot.get("library_total") == 3
            and settings.statistics_panel.snapshot.get("total_sessions") == 0,
            "statistics dashboard reflects the current library",
        )
        stats_panel = settings.statistics_panel
        stats_cards = (
            stats_panel.library_card,
            stats_panel.sessions_card,
            stats_panel.success_card,
            stats_panel.reliability_card,
        )
        check(
            stats_panel.refresh_button.geometry().right() < stats_panel.reset_button.geometry().left()
            and all(
                left.geometry().right() < right.geometry().left()
                for left, right in zip(stats_cards[:-1], stats_cards[1:], strict=True)
            )
            and stats_panel.refresh_button.geometry().bottom() < stats_panel.library_card.geometry().top()
            and stats_panel.library_card.geometry().bottom() < stats_panel.library_panel.geometry().top()
            and stats_panel.library_panel.geometry().bottom()
            < stats_panel.outcome_card.geometry().top(),
            "statistics dashboard controls never overlap",
        )
        session_cards = (
            stats_panel.outcome_card, stats_panel.games_card, stats_panel.duration_card,
        )
        check(
            all(
                left.geometry().right() < right.geometry().left()
                for left, right in zip(session_cards[:-1], session_cards[1:], strict=True)
            )
            and {card.geometry().bottom() for card in session_cards} == {
                stats_panel.outcome_card.geometry().bottom()
            },
            "last-session cards sit in one row without overlapping",
        )
        settings._set_section(0)
        # Уменьшаем, а не увеличиваем: стандартное значение — 60 (потолок), и «+» был бы no-op.
        old_concurrent = window.concurrent_value
        settings._pending_decrement_games()
        check(window.concurrent_value == old_concurrent - 1, "concurrent-games setting saves immediately")
        settings.unlock_achievements_btn.setChecked(True)
        settings._pending_toggle_unlock()
        check(window.unlock_achievements is True, "achievement toggle saves immediately")
        settings.loop_boost_btn.setChecked(True)
        settings._pending_toggle_loop()
        check(window.loop_boost is True, "loop boost toggle saves immediately")
        settings._pending_launch_cd_from = 50
        settings._pending_launch_cd_to = 10
        settings._normalize_cd_ranges()
        check(settings._pending_launch_cd_to == 55, "professional cooldown ranges keep the minimum spread")

        # Направленный разрыв: редактируем одну границу — следует другая.
        settings._pending_finish_cd_from = 2
        settings._pending_finish_cd_to = 6
        settings._enforce_cd_gap('finish', 'from')
        check(settings._pending_finish_cd_to == 7, "raising min pushes max to keep the 5s spread")
        settings._pending_slot_cd_from = 20
        settings._pending_slot_cd_to = 22
        settings._enforce_cd_gap('slot', 'to')
        check(settings._pending_slot_cd_from == 17, "lowering max pulls min to keep the 5s spread")

        # --- Вкладка «Общее»: тумблер быстрого копирования, конфиги, очистка кэша ---
        settings._set_section(0)
        settings.btn_fast_copy_toggle.setChecked(True)
        settings._pending_toggle_fast_copy()
        check(window.fast_paste_enabled is True, "fast-copy toggle saves immediately")

        cfg_dir = settings._configs_dir()
        check(Path(temp_dir).resolve() in cfg_dir.resolve().parents,
              "config profiles are stored inside the isolated data dir")
        before = len(list(cfg_dir.glob('*.json')))
        settings._pending_games_value = 42
        settings._save_new_config()
        check(len(list(cfg_dir.glob('*.json'))) == before + 1 and len(settings._configs) == before + 1,
              "saving a config writes a new profile file")

        settings._pending_games_value = 7
        settings._cfg_index = len(settings._configs) - 1  # только что сохранённый профиль
        settings._load_selected_config()
        check(settings._pending_games_value == 42, "loading a config restores its saved values")

        index_before = settings._cfg_index
        settings._switch_config(1)
        settings._switch_config(-1)
        check(settings._cfg_index == index_before, "config prev/next returns to the same profile")

        # Фоновая операция возвращает ровно то состояние кнопок, что было до неё.
        settings.btn_cfg_load.setEnabled(False)
        settings._set_background_busy(True)
        settings._set_background_busy(False)
        check(settings.btn_cfg_load.isEnabled() is False,
              "background task restores the previous button state instead of enabling all")
        settings.btn_cfg_load.setEnabled(True)

        # Профили копились без возможности удалить их из интерфейса.
        before_delete = len(settings._configs)
        settings._delete_selected_config()
        check(len(list(cfg_dir.glob('*.json'))) == before_delete - 1
              and len(settings._configs) == before_delete - 1,
              "deleting a config removes the profile file")

        (Path(temp_dir) / 'games_upload.json').write_text('[]', encoding='utf-8')
        black_list = Path(temp_dir) / 'black_list.json'
        black_list.write_text('[{"appid": "570", "name": "Dota 2", "status": "err"}]', encoding='utf-8')
        settings._on_clear_cache()
        check(not (Path(temp_dir) / 'games_upload.json').exists(),
              "clear-cache removes the app-list cache file")
        # Единственный способ вернуть игру из чёрного списка — он обязан работать.
        check(json.loads(black_list.read_text(encoding='utf-8')) == [],
              "clear-cache also empties the blacklist so games become boostable again")

        settings._clear_table()
        check(main_screen.games == [], "clear-table action empties the user table")

        # «Отрисовка таблицы» реально меняет плотность: меньше строк -> выше строка.
        main_screen.visible_rows = 5
        main_screen.apply_row_density()
        tall_row = main_screen.game_table.verticalHeader().defaultSectionSize()
        main_screen.visible_rows = 20
        main_screen.apply_row_density()
        short_row = main_screen.game_table.verticalHeader().defaultSectionSize()
        check(tall_row > short_row, "table-render setting changes the row height (density)")

        created_boosters = []

        def booster_factory(_path):
            booster = FakeBooster()
            created_boosters.append(booster)
            return booster

        settings_module.SteamBooster = booster_factory
        settings_module.SteamAppLookup = FakeLookup
        settings._on_add_all_games()
        wait_until(
            app,
            lambda: len(main_screen.games) == 3 and created_boosters and created_boosters[-1].shutdown_called == 1 and settings._add_all_task is None,
            "add-all-games imports owned games and shuts down the checker",
        )
        app.processEvents()
        check({g["appid"] for g in main_screen.games} == {"10", "20", "570"}, "add-all-games avoids bad and unowned AppIDs")

        settings._on_add_all_games()
        wait_until(
            app,
            lambda: len(created_boosters) >= 2 and created_boosters[-1].shutdown_called == 1 and settings._add_all_task is None,
            "running add-all-games again completes without duplicates",
        )
        check(len(main_screen.games) == 3, "add-all-games is idempotent for already-listed games")

        window.loop_boost = False
        window.config["loop_boost"] = False
        window.concurrent_value = 2
        window.duration_value = 30
        window.unlock_achievements = True
        fake_booster.start_calls.clear()
        main_screen.is_boosting = True
        window.handle_start_boost()
        check(fake_booster.start_calls == [], "start button is ignored while a boost is already running")
        main_screen.is_boosting = False

        window.handle_start_boost()
        wait_until(app, lambda: main_screen.is_boosting is False, "boost completion resets running state")
        check(len(fake_booster.start_calls) == 1, "start boost calls the booster once")
        check(fake_booster.start_calls[0]["num_slots"] == 2, "boost uses configured parallel slot count")
        check(fake_booster.start_calls[0]["unlock_achievements"] is True, "boost passes achievement-unlock setting")
        check({g["status"] for g in main_screen.games} == {"Готово"}, "boost completion updates all statuses")
        settings._refresh_statistics()
        check(
            settings.statistics_panel.snapshot.get("total_sessions") == 1
            and settings.statistics_panel.snapshot.get("successful_games") == 3,
            "completed boost is persisted in statistics",
        )

        # Авточистка убирает только успешные игры: провалы и необработанное остаются,
        # иначе один прогон сносил бы весь многотысячный список без предупреждения.
        window.config['auto_clean_table'] = True
        main_screen.games = [
            {'appid': '10', 'name': 'Done', 'status': 'Готово'},
            {'appid': '20', 'name': 'Failed', 'status': 'Ошибка: не удалось сохранить достижения (код 2)'},
            {'appid': '30', 'name': 'Untouched', 'status': 'Ожидание'},
        ]
        window._auto_clean_finished_games()
        check([g['appid'] for g in main_screen.games] == ['20', '30'],
              "auto-clean removes finished games but keeps failures and untouched ones")
        check([g['appid'] for g in game_storage.load_games()] == ['20', '30'],
              "auto-clean persists the surviving games")
        window.config['auto_clean_table'] = False

        # Мёртвые ловушки: stop_boost помечал бы все игры «Готово».
        check(not hasattr(main_screen, 'start_boost') and not hasattr(main_screen, 'stop_boost'),
              "dangerous unused start_boost/stop_boost helpers are gone")

        # Одна «грязная» запись роняла завершение сессии и теряла все статусы.
        main_screen.games = [{'appid': '10', 'name': 'ok', 'status': 'Ожидание'}, 'мусор']
        main_screen.set_all_status('В очереди')
        main_screen.finalize_session_statuses(stopped=False)
        check(main_screen.games[0]['status'] == 'Не выполнено',
              "malformed rows never break status finalization")
        # Возвращаем корректный список: дальше идут проверки, ожидающие только словари.
        main_screen.games = [
            {'appid': '10', 'name': 'Alpha', 'status': 'Ожидание'},
            {'appid': '20', 'name': 'Beta', 'status': 'Ожидание'},
        ]

        main_screen.is_boosting = True
        window.handle_stop_boost()
        app.processEvents()
        check(fake_booster.stopped is True, "stop button calls booster stop")
        check(main_screen.is_boosting is False, "stop button clears running state")
        check({g["status"] for g in main_screen.games} == {"Остановлено"}, "stop button marks games as stopped")

        game_storage.save_games([
            {"appid": 10, "name": 570, "status": None},
            {"broken": True},
        ])
        stored = game_storage.load_games()
        check(stored == [{"appid": "10", "name": "570", "status": "Ожидание"}], "storage normalizes malformed game rows")

        check_update_notification(app, window, main_window_module, Path(temp_dir))

        window.close()
        app.processEvents()
        app.quit()


if __name__ == "__main__":
    main()
