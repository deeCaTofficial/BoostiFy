import os
import sys
import tempfile
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


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
        for appid in appids:
            callback(appid, "Бустится")
        callback(
            "progress",
            {
                "games_done": len(appids),
                "games_total": len(appids),
                "final_eta_sec": 0,
            },
        )
        for appid in appids:
            callback(appid, "Готово")
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
    from BoostiFy.GUI.core import game_storage

    game_storage.configure_storage(temp_dir)
    game_storage.ensure_default_config()
    return game_storage


def patch_dialogs():
    from PyQt6.QtWidgets import QDialog
    from BoostiFy.GUI.widgets import toast

    toast.InfoDialog.exec = lambda self: QDialog.DialogCode.Accepted
    toast.CustomConfirmDialog.exec = lambda self: QDialog.DialogCode.Accepted


def main():
    with tempfile.TemporaryDirectory(prefix="boostify-functional-qa-") as temp_dir:
        game_storage = configure_isolated_storage(temp_dir)
        patch_dialogs()

        from PyQt6.QtCore import Qt, QEvent
        from PyQt6.QtGui import QGuiApplication, QKeyEvent
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtCore import QItemSelectionModel
        import BoostiFy.GUI.screens.settings_screen as settings_module
        import BoostiFy.GUI.main_window as main_window_module

        main_window_module.runtime_is_ready = lambda: True
        main_window_module.missing_runtime_files = lambda: []
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
            stats_panel.title_label.geometry().right() < stats_panel.refresh_button.geometry().left()
            and stats_panel.refresh_button.geometry().right() < stats_panel.reset_button.geometry().left()
            and all(
                left.geometry().right() < right.geometry().left()
                for left, right in zip(stats_cards[:-1], stats_cards[1:], strict=True)
            )
            and stats_panel.library_panel.geometry().bottom()
            < stats_panel.activity_panel.geometry().top()
            and stats_panel.activity_panel.geometry().bottom() < stats_panel.hint_label.geometry().top(),
            "statistics dashboard controls never overlap",
        )
        settings._set_section(0)
        old_concurrent = window.concurrent_value
        settings._pending_increment_games()
        check(window.concurrent_value == old_concurrent + 1, "concurrent-games setting saves immediately")
        settings.unlock_achievements_btn.setChecked(True)
        settings._pending_toggle_unlock()
        check(window.unlock_achievements is True, "achievement toggle saves immediately")
        settings.loop_boost_btn.setChecked(True)
        settings._pending_toggle_loop()
        check(window.loop_boost is True, "loop boost toggle saves immediately")
        settings._pending_launch_cd_from = 50
        settings._pending_launch_cd_to = 10
        settings._normalize_cd_ranges()
        check(settings._pending_launch_cd_to == 50, "professional cooldown ranges normalize safely")

        settings._clear_table()
        check(main_screen.games == [], "clear-table action empties the user table")

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

        window.close()
        app.processEvents()
        app.quit()


if __name__ == "__main__":
    main()
