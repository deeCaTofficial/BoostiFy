# main_window.py — точка входа для BoostiFy GUI

from PyQt6.QtWidgets import QMainWindow, QFrame, QStackedWidget, QApplication, QLabel, QDialog
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from BoostiFy.GUI.widgets.custom_title_bar import CustomTitleBar
from BoostiFy.GUI.screens.main_screen import MainScreenWidget
from BoostiFy.GUI.screens.settings_screen import SettingsScreenWidget
from BoostiFy.GUI.core.game_storage import DEFAULT_CONFIG, load_config, normalize_config, save_config, save_games
from BoostiFy.GUI.core.statistics_storage import (
    classify_game_statuses,
    discard_statistics_session,
    finish_statistics_session,
    start_statistics_session,
)
from BoostiFy.GUI.utils.styles import BG_COLOR, BORDER_RADIUS
from BoostiFy.GUI.widgets.toast import CustomConfirmDialog, InfoDialog
from BoostiFy.core.runtime_paths import BACKGROUND_WORKER, missing_runtime_files, runtime_is_ready
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BOOSTER_EXECUTABLE = BACKGROUND_WORKER


class MainWindow(QMainWindow):
    toast_signal = pyqtSignal(str, int)

    def __init__(self):
        super().__init__()
        self.setFixedSize(960, 555)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # Устанавливаем иконку приложения (панель задач / Alt-Tab)
        try:
            icon_path = PROJECT_ROOT / "BoostiFy" / "Assets" / "BoostiFyLogo.png"
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass
        
        self.main_background = QFrame(self)
        self.main_background.setGeometry(0, 0, 960, 555)
        self.main_background.setStyleSheet(f"background-color: {BG_COLOR}; border-radius: {BORDER_RADIUS}px;")
        
        self.stacked_widget = QStackedWidget(self.main_background)
        self.stacked_widget.setGeometry(0, 0, 960, 555)
        self.stacked_widget.setStyleSheet("background: transparent;")
        
        self.title_bar = CustomTitleBar(self)
        self.title_bar.setGeometry(0, 0, 960, 30)
        
        # Логотип слева, перекрывающийся с титл-баром и доходящий до области поиска
        try:
            logo_path = PROJECT_ROOT / "BoostiFy" / "Assets" / "BoostiFy.png"
            if logo_path.exists():
                self.top_logo_label = QLabel(self.main_background)
                pixmap = QPixmap(str(logo_path))
                scaled = pixmap.scaledToHeight(38, Qt.TransformationMode.SmoothTransformation)
                self.top_logo_label.setPixmap(scaled)
                # Центрируем по горизонтали относительно области поиска (x=30..310)
                self.top_logo_label.setGeometry(30, 4, 280, 40)
                self.top_logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                # Не блокируем перетаскивание окна за титл-бар
                self.top_logo_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                self.top_logo_label.raise_()
        except Exception:
            pass

        self.main_screen = MainScreenWidget(self)
        self.settings_screen = SettingsScreenWidget()
        self.settings_screen.main_window = self
        
        self.stacked_widget.addWidget(self.main_screen)
        self.stacked_widget.addWidget(self.settings_screen)
        
        # Подключение сигналов и слотов
        self.main_screen.settings_requested.connect(self.show_settings)
        self.settings_screen.back_requested.connect(self.show_main)
        self.main_screen.add_game_requested.connect(self.handle_add_game)
        self.main_screen.del_game_requested.connect(self.handle_del_game)
        self.main_screen.start_boost_requested.connect(self.handle_start_boost)
        self.main_screen.stop_boost_requested.connect(self.handle_stop_boost)
        self.settings_screen.settings_changed.connect(self.apply_settings_from_ui)
        
        # Загрузка конфигурации
        self.config = load_config()
        self.concurrent_value = self.config.get('concurrent_value', DEFAULT_CONFIG['concurrent_value'])
        config_time = self.config.get('duration_value', DEFAULT_CONFIG['duration_value'])
        MIN_TIME_SECONDS = 30
        self.duration_value = max(config_time, MIN_TIME_SECONDS)
        self.unlock_achievements = self.config.get('unlock_achievements', DEFAULT_CONFIG['unlock_achievements'])
        self.fast_paste_enabled = self.config.get('fast_paste_enabled', DEFAULT_CONFIG['fast_paste_enabled'])
        self.time_mode = self.config.get('time_mode', DEFAULT_CONFIG['time_mode'])
        self.loop_boost = self.config.get('loop_boost', False)
        self._stop_requested = False
        self._stats_session_id = None
        self.launch_cd_range = (
            self.config.get('launch_cd_from', 5),
            self.config.get('launch_cd_to', 35)
        )
        self.finish_cd_range = (
            self.config.get('finish_cd_from', 5),
            self.config.get('finish_cd_to', 35)
        )
        self.slot_cd_range = (
            self.config.get('slot_cd_from', 60),
            self.config.get('slot_cd_to', 90)
        )
        self.main_screen.visible_rows = self.config.get('table_visible_rows', self.main_screen.visible_rows)

        self.booster = self.main_screen.booster
        self.main_screen.boost_finished_signal.connect(self._on_boost_finished)
        self._refresh_runtime_state()
        
        self.show_main()
        self.main_screen.update_time_label()

    def show_main(self):
        self.stacked_widget.setCurrentIndex(0)
        self.main_screen.update_time_label()

    def show_settings(self):
        if self.main_screen.is_boosting:
            InfoDialog(self, 'Настройки заблокированы до завершения текущей сессии.').exec()
            return
        self.stacked_widget.setCurrentIndex(1)
        self.settings_screen.set_values_from_config(
            self.concurrent_value,
            self.duration_value,
            self.unlock_achievements,
            self.fast_paste_enabled,
            self.time_mode
        )
        self.settings_screen.set_extra_values_from_config(self.config)
        self.main_screen.update_time_label()

    def apply_settings_from_ui(self, games, time, unlock, fast_copy, time_mode):
        safe = normalize_config({
            **self.config,
            'concurrent_value': games,
            'duration_value': time,
            'unlock_achievements': unlock,
            'fast_paste_enabled': fast_copy,
            'time_mode': time_mode,
        })
        self.concurrent_value = safe['concurrent_value']
        self.duration_value = safe['duration_value']
        self.unlock_achievements = safe['unlock_achievements']
        self.fast_paste_enabled = safe['fast_paste_enabled']
        self.time_mode = safe['time_mode']
        self.loop_boost = self.config.get('loop_boost', False)
        self.launch_cd_range = (
            self.config.get('launch_cd_from', 5),
            self.config.get('launch_cd_to', 35)
        )
        self.finish_cd_range = (
            self.config.get('finish_cd_from', 5),
            self.config.get('finish_cd_to', 35)
        )
        self.slot_cd_range = (
            self.config.get('slot_cd_from', 60),
            self.config.get('slot_cd_to', 90)
        )
        self.config.update(safe)
        save_config(self.config)
        self.main_screen.update_time_label()

    def handle_add_game(self, text):
        if text:
            self.main_screen.try_add_game(text)

    def handle_del_game(self):
        self.main_screen.remove_selected_game()

    def handle_start_boost(self):
        if self.main_screen.is_boosting:
            return
        self._refresh_runtime_state()
        if not runtime_is_ready():
            InfoDialog(self, self._runtime_error_message()).exec()
            return
        if self.booster.is_busy:
            InfoDialog(self, 'Предыдущая сессия ещё завершает процессы. Подождите несколько секунд.').exec()
            return
        appids = [str(g.get('appid')) for g in self.main_screen.games if isinstance(g, dict) and g.get('appid')]
        if not appids:
            InfoDialog(self, 'Список игр пуст. Сначала добавьте хотя бы одну игру.').exec()
            return
        if self.unlock_achievements:
            confirm = CustomConfirmDialog(
                self,
                'Разблокировка достижений изменяет данные Steam и может быть необратимой. Продолжить?',
                'Продолжить',
                'Отмена',
            )
            if confirm.exec() != QDialog.DialogCode.Accepted:
                return
        self._stop_requested = False

        def status_callback(event_type, data):
            if event_type == 'progress':
                self.main_screen.update_progress_signal.emit(data)
            elif event_type == 'boost' and data == 'finished':
                self.main_screen.boost_finished_signal.emit()
            else:
                self.main_screen.set_game_status_signal.emit(str(event_type), str(data))

        self.main_screen.set_all_status('В очереди')
        self.main_screen.set_boost_controls(True)
        try:
            statistics_session_id = start_statistics_session(len(appids))
        except (OSError, ValueError) as error:
            print(f'Не удалось начать запись статистики: {error}')
            statistics_session_id = None
        self._stats_session_id = statistics_session_id
        try:
            self.booster.start_boost_sliding(
                appids,
                self.concurrent_value,
                self.duration_value,
                status_callback,
                self.unlock_achievements,
                launch_cd_range=self.launch_cd_range,
                finish_cd_range=self.finish_cd_range,
                slot_cd_range=self.slot_cd_range
            )
        except Exception as e:
            if statistics_session_id:
                try:
                    discard_statistics_session(statistics_session_id)
                except OSError as error:
                    print(f'Не удалось отменить запись статистики: {error}')
            if self._stats_session_id == statistics_session_id:
                self._stats_session_id = None
            self.main_screen.set_all_status('Ошибка запуска')
            self.main_screen.set_boost_controls(False)
            InfoDialog(self, f"Не удалось запустить буст: {e}").exec()


    def handle_stop_boost(self):
        if not self.main_screen.is_boosting:
            return
        self._stop_requested = True
        self.main_screen.set_boost_controls(True, stopping=True)
        self.main_screen.set_all_status('Остановка...')
        if not self.booster.stop_boost():
            self.main_screen.boost_finished_signal.emit()

    def _on_boost_finished(self):
        self.main_screen.finalize_session_statuses(stopped=self._stop_requested)
        self._finish_statistics_session(stopped=self._stop_requested)
        if self.config.get('auto_clean_table', False):
            self.main_screen.games = []
            save_games([])
            self.main_screen.update_game_list()
            self.main_screen.update_time_label()
            self.main_screen.set_boost_controls(False)
            return
        if self.loop_boost and not self._stop_requested and self.main_screen.games:
            QTimer.singleShot(1000, self.handle_start_boost)

    def _finish_statistics_session(self, *, stopped, interrupted=False):
        session_id = self._stats_session_id
        if not session_id:
            return False
        self._stats_session_id = None
        counts = classify_game_statuses(self.main_screen.games)
        try:
            saved = finish_statistics_session(
                session_id,
                successful_games=counts['successful'],
                failed_games=counts['failed'],
                skipped_games=counts['skipped'],
                stopped=stopped,
                interrupted=interrupted,
            )
        except (OSError, ValueError) as error:
            print(f'Не удалось сохранить статистику: {error}')
            saved = False
        refresh = getattr(self.settings_screen, '_refresh_statistics', None)
        if callable(refresh):
            refresh()
        return saved

    def _runtime_error_message(self):
        missing = ', '.join(path.name for path in missing_runtime_files())
        return (
            f'Steam runtime не готов. Отсутствуют: {missing}.\n\n'
            'Выполните: python BoostiFy/runtime/build.py'
        )

    def _refresh_runtime_state(self):
        ready = runtime_is_ready()
        message = '' if ready else self._runtime_error_message()
        self.main_screen.set_runtime_available(ready, message)
        setter = getattr(self.settings_screen, 'set_runtime_available', None)
        if callable(setter):
            setter(ready, message)

    def closeEvent(self, event):
        """Этот метод вызывается при закрытии окна."""
        self._stop_requested = True
        add_task = getattr(self.main_screen, '_add_task', None)
        if add_task is not None:
            add_task.cancel()
        cancel_add_all = getattr(self.settings_screen, 'cancel_background_operations', None)
        if callable(cancel_add_all):
            cancel_add_all()
        if hasattr(self, 'booster') and self.booster:
            # Останавливаем все процессы буста
            self.booster.stop_boost()
            # Корректно завершаем работу C#-сервера проверки владения
            if hasattr(self.booster, 'shutdown_server'):
                 self.booster.shutdown_server()
            self.booster.wait_for_stop(timeout=5)
        if self._stats_session_id:
            self.main_screen.finalize_session_statuses(stopped=True)
            self._finish_statistics_session(stopped=True, interrupted=True)
        super().closeEvent(event)

# Точка входа
if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
