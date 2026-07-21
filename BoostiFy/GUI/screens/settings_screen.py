# settings_screen.py — экран настроек приложения

from PyQt6.QtWidgets import QWidget, QPushButton, QLabel, QProgressBar, QDialog, QStackedWidget
from PyQt6.QtCore import pyqtSignal, QThreadPool
from BoostiFy.GUI.utils.styles import (
    BUTTON_STYLE,
    LABEL_AS_BUTTON_STYLE,
    NAV_BUTTON_STYLE,
    TOGGLE_BUTTON_STYLE,
)
from BoostiFy.GUI.utils.helpers import format_time_verbose
from BoostiFy.GUI.widgets.toast import CustomConfirmDialog, InfoDialog
from BoostiFy.core.booster import SteamBooster
from BoostiFy.GUI.core.game_storage import (
    DEFAULT_CONFIG,
    UPLOAD_DIR,
    load_config,
    load_games,
    normalize_config,
    save_config,
    save_games,
)
from BoostiFy.GUI.core.statistics_storage import load_statistics, reset_statistics
from BoostiFy.GUI.screens.statistics_screen import StatisticsPanel
from BoostiFy.core.runtime_paths import BACKGROUND_WORKER
from BoostiFy.core.steam_lookup import SteamAppLookup
from BoostiFy.GUI.core.async_tasks import BackgroundTask
from pathlib import Path
import json
import time

class SettingsScreenWidget(QWidget):
    back_requested = pyqtSignal()
    # Сигнал совместим с MainWindow.apply_settings_from_ui
    settings_changed = pyqtSignal(int, int, bool, bool, int)

    def set_toast_callback(self, callback):
        self._toast_callback = callback

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: transparent;")

        # ------- Левая колонка (навигация по разделам)
        self.btn_left_general = QPushButton("Общее", self)
        self.btn_left_general.setGeometry(30, 45, 280, 45)
        self.btn_left_boost = QPushButton("Буст", self)
        self.btn_left_boost.setGeometry(30, 120, 280, 45)
        self.btn_left_table = QPushButton("Таблица", self)
        self.btn_left_table.setGeometry(30, 195, 280, 45)
        self.btn_left_pro = QPushButton("Профессиональное", self)
        self.btn_left_pro.setGeometry(30, 270, 280, 45)
        self.btn_left_stats = QPushButton("Статистика", self)
        self.btn_left_stats.setGeometry(30, 345, 280, 45)
        self.btn_back_left = QPushButton("Назад", self)
        self.btn_back_left.setGeometry(30, 420, 280, 45)
        self.btn_back_left.clicked.connect(self._on_back_clicked)

        self._section_buttons = [
            self.btn_left_general,
            self.btn_left_boost,
            self.btn_left_table,
            self.btn_left_pro,
            self.btn_left_stats,
        ]
        for button in self._section_buttons:
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setStyleSheet(NAV_BUTTON_STYLE)
        self.btn_back_left.setStyleSheet(BUTTON_STYLE)

        # ------- Правая часть — стек страниц
        self.right_stack = QStackedWidget(self)
        self.right_stack.setGeometry(340, 45, 590, 420)

        # ====== Страница "Общее"
        page_general = QWidget()
        # Очистка кэша
        self.btn_clear_cache = QPushButton("Очистить кэш", page_general)
        self.btn_clear_cache.setGeometry(0, 0, 290, 45)
        self.btn_clear_cache.clicked.connect(self._on_clear_cache)
        # Быстрое копирование (toggle)
        self.btn_fast_copy_toggle = QPushButton("Быстрое копирование", page_general)
        self.btn_fast_copy_toggle.setGeometry(300, 0, 290, 45)
        self.btn_fast_copy_toggle.setCheckable(True)
        self.btn_fast_copy_toggle.setStyleSheet(TOGGLE_BUTTON_STYLE)
        # Выбор/сохранение конфигов
        self.btn_cfg_prev = QPushButton("<", page_general)
        self.btn_cfg_prev.setGeometry(0, 75, 45, 45)
        self.btn_cfg_prev.clicked.connect(lambda: self._switch_config(-1))
        self.lbl_cfg_name = QLabel("Выбор конфига", page_general)
        self.lbl_cfg_name.setGeometry(55, 75, 480, 45)
        self.lbl_cfg_name.setStyleSheet(LABEL_AS_BUTTON_STYLE)
        self.btn_cfg_next = QPushButton(">", page_general)
        self.btn_cfg_next.setGeometry(545, 75, 45, 45)
        self.btn_cfg_next.clicked.connect(lambda: self._switch_config(1))
        self.btn_cfg_save = QPushButton("Сохранить новый конфиг", page_general)
        self.btn_cfg_save.setGeometry(0, 150, 290, 45)
        self.btn_cfg_save.clicked.connect(self._save_new_config)
        self.btn_cfg_load = QPushButton("Загрузить конфиг", page_general)
        self.btn_cfg_load.setGeometry(300, 150, 290, 45)
        self.btn_cfg_load.clicked.connect(self._load_selected_config)
        for w in page_general.findChildren(QPushButton):
            if not w.isCheckable():
                w.setStyleSheet(BUTTON_STYLE)
        for w in page_general.findChildren(QLabel):
            w.setStyleSheet(LABEL_AS_BUTTON_STYLE)
        self.right_stack.addWidget(page_general)

        # ====== Страница "Буст"
        page_boost = QWidget()
        # Параллельных игр
        QLabel("Параллельных игр", page_boost).setGeometry(0, 0, 410, 45)
        self.games_decrement_btn = QPushButton("-", page_boost)
        self.games_decrement_btn.setGeometry(425, 0, 45, 45)
        self.games_value_label = QLabel("15", page_boost)
        self.games_value_label.setGeometry(485, 0, 45, 45)
        self.games_increment_btn = QPushButton("+", page_boost)
        self.games_increment_btn.setGeometry(545, 0, 45, 45)
        # Время на пачку
        QLabel("Время на пачку", page_boost).setGeometry(0, 75, 410, 45)
        self.time_decrement_btn = QPushButton("-", page_boost)
        self.time_decrement_btn.setGeometry(425, 75, 45, 45)
        self.time_value_label = QLabel("30с.", page_boost)
        self.time_value_label.setGeometry(485, 75, 45, 45)
        self.time_increment_btn = QPushButton("+", page_boost)
        self.time_increment_btn.setGeometry(545, 75, 45, 45)
        self.time_options = ([f"{s}с." for s in range(30, 60)] +
                             [f"{m}м." for m in range(1, 60)] +
                             [f"{h}ч." for h in range(1, 24)] +
                             [f"{d}д." for d in range(1, 8)])
        try:
            self.current_time_index = self.time_options.index(self.time_value_label.text())
        except ValueError:
            self.current_time_index = 0
        # Тогглы
        self.unlock_achievements_btn = QPushButton("Авто разблокировка ачивок", page_boost)
        self.unlock_achievements_btn.setGeometry(0, 150, 287, 45)
        self.unlock_achievements_btn.setCheckable(True)
        self.unlock_achievements_btn.setStyleSheet(TOGGLE_BUTTON_STYLE)
        self.loop_boost_btn = QPushButton("Зацикленный буст", page_boost)
        self.loop_boost_btn.setGeometry(303, 150, 287, 45)
        self.loop_boost_btn.setCheckable(True)
        self.loop_boost_btn.setStyleSheet(TOGGLE_BUTTON_STYLE)
        for w in page_boost.findChildren(QPushButton):
            if not w.isCheckable():
                w.setStyleSheet(BUTTON_STYLE)
        for w in page_boost.findChildren(QLabel):
            w.setStyleSheet(LABEL_AS_BUTTON_STYLE)
        self.right_stack.addWidget(page_boost)

        # ====== Страница "Таблица"
        page_table = QWidget()
        self.btn_clear_table = QPushButton("Очистить таблицу", page_table)
        self.btn_clear_table.setGeometry(0, 0, 287, 45)
        self.btn_clear_table.clicked.connect(self._clear_table)
        self.auto_clean_btn = QPushButton("Авто чистка таблицы", page_table)
        self.auto_clean_btn.setGeometry(303, 0, 287, 45)
        self.auto_clean_btn.setCheckable(True)
        self.auto_clean_btn.setStyleSheet(TOGGLE_BUTTON_STYLE)
        self.btn_add_all_games = QPushButton("Добавить все игры", page_table)
        self.btn_add_all_games.setGeometry(0, 75, 590, 45)
        self.btn_add_all_games.clicked.connect(self._on_add_all_games)
        QLabel("Отрисовка таблицы", page_table).setGeometry(0, 150, 410, 45)
        self.table_rows_decrement_btn = QPushButton("-", page_table)
        self.table_rows_decrement_btn.setGeometry(425, 150, 45, 45)
        self.table_rows_value_label = QLabel("15", page_table)
        self.table_rows_value_label.setGeometry(485, 150, 45, 45)
        self.table_rows_increment_btn = QPushButton("+", page_table)
        self.table_rows_increment_btn.setGeometry(545, 150, 45, 45)
        for w in page_table.findChildren(QPushButton):
            if not w.isCheckable():
                w.setStyleSheet(BUTTON_STYLE)
        for w in page_table.findChildren(QLabel):
            w.setStyleSheet(LABEL_AS_BUTTON_STYLE)
        self.right_stack.addWidget(page_table)

        # ====== Страница "Профессиональное"
        page_pro = QWidget()
        # КД начала
        self.btn_cd1_from_minus = QPushButton("-", page_pro)
        self.btn_cd1_from_minus.setGeometry(0, 0, 45, 45)
        self.cd1_from_label = QLabel("от 5с.", page_pro)
        self.cd1_from_label.setGeometry(55, 0, 90, 45)
        self.btn_cd1_from_plus = QPushButton("+", page_pro)
        self.btn_cd1_from_plus.setGeometry(155, 0, 45, 45)
        self.cd1_title_label = QLabel("КД начала", page_pro)
        self.cd1_title_label.setGeometry(210, 0, 170, 45)
        self.btn_cd1_to_minus = QPushButton("-", page_pro)
        self.btn_cd1_to_minus.setGeometry(390, 0, 45, 45)
        self.cd1_to_label = QLabel("до 35с.", page_pro)
        self.cd1_to_label.setGeometry(445, 0, 90, 45)
        self.btn_cd1_to_plus = QPushButton("+", page_pro)
        self.btn_cd1_to_plus.setGeometry(545, 0, 45, 45)
        # КД завершения
        self.btn_cd2_from_minus = QPushButton("-", page_pro)
        self.btn_cd2_from_minus.setGeometry(0, 75, 45, 45)
        self.cd2_from_label = QLabel("от 5с.", page_pro)
        self.cd2_from_label.setGeometry(55, 75, 90, 45)
        self.btn_cd2_from_plus = QPushButton("+", page_pro)
        self.btn_cd2_from_plus.setGeometry(155, 75, 45, 45)
        self.cd2_title_label = QLabel("КД завершения", page_pro)
        self.cd2_title_label.setGeometry(210, 75, 170, 45)
        self.btn_cd2_to_minus = QPushButton("-", page_pro)
        self.btn_cd2_to_minus.setGeometry(390, 75, 45, 45)
        self.cd2_to_label = QLabel("до 35с.", page_pro)
        self.cd2_to_label.setGeometry(445, 75, 90, 45)
        self.btn_cd2_to_plus = QPushButton("+", page_pro)
        self.btn_cd2_to_plus.setGeometry(545, 75, 45, 45)
        # КД между
        self.btn_cd3_from_minus = QPushButton("-", page_pro)
        self.btn_cd3_from_minus.setGeometry(0, 150, 45, 45)
        self.cd3_from_label = QLabel("от 60с.", page_pro)
        self.cd3_from_label.setGeometry(55, 150, 90, 45)
        self.btn_cd3_from_plus = QPushButton("+", page_pro)
        self.btn_cd3_from_plus.setGeometry(155, 150, 45, 45)
        self.cd3_title_label = QLabel("КД между", page_pro)
        self.cd3_title_label.setGeometry(210, 150, 170, 45)
        self.btn_cd3_to_minus = QPushButton("-", page_pro)
        self.btn_cd3_to_minus.setGeometry(390, 150, 45, 45)
        self.cd3_to_label = QLabel("до 90с.", page_pro)
        self.cd3_to_label.setGeometry(445, 150, 90, 45)
        self.btn_cd3_to_plus = QPushButton("+", page_pro)
        self.btn_cd3_to_plus.setGeometry(545, 150, 45, 45)
        for w in page_pro.findChildren(QPushButton):
            if not w.isCheckable():
                w.setStyleSheet(BUTTON_STYLE)
        for w in page_pro.findChildren(QLabel):
            w.setStyleSheet(LABEL_AS_BUTTON_STYLE)
        self.right_stack.addWidget(page_pro)

        # ====== Страница "Статистика"
        page_stats = QWidget()
        self.statistics_panel = StatisticsPanel(page_stats)
        self.statistics_panel.setGeometry(0, 0, 590, 420)
        self.statistics_panel.refresh_requested.connect(self._refresh_statistics)
        self.statistics_panel.reset_requested.connect(self._reset_statistics)
        self.right_stack.addWidget(page_stats)

        # ------- Нижний прогресс-бар (как и раньше)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setGeometry(30, 495, 900, 30)
        self.progress_bar.setStyleSheet("QProgressBar { background-color: #2b3541; color: #dcdedf; border: none; border-radius: 10px; text-align: center; font-size: 18px; } QProgressBar::chunk { background-color: #1A9AF3; border-radius: 10px; }")
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        # --- Текущие значения настроек
        self._pending_games_value = 15
        self._pending_time_value = 30
        self._pending_unlock_achievements = False
        self._pending_fast_copy = False
        self._pending_time_mode = 0
        self._pending_loop_boost = False
        self._pending_table_rows = 15
        self._pending_auto_clean_table = False
        self._pending_launch_cd_from = 5
        self._pending_launch_cd_to = 35
        self._pending_finish_cd_from = 5
        self._pending_finish_cd_to = 35
        self._pending_slot_cd_from = 60
        self._pending_slot_cd_to = 90

        # Подключение событий (автосохранение)
        self.games_increment_btn.clicked.connect(self._pending_increment_games)
        self.games_decrement_btn.clicked.connect(self._pending_decrement_games)
        self.time_increment_btn.clicked.connect(self._pending_increment_time)
        self.time_decrement_btn.clicked.connect(self._pending_decrement_time)
        self.unlock_achievements_btn.clicked.connect(self._pending_toggle_unlock)
        self.loop_boost_btn.clicked.connect(self._pending_toggle_loop)
        self.btn_fast_copy_toggle.clicked.connect(self._pending_toggle_fast_copy)
        self.table_rows_increment_btn.clicked.connect(self._pending_increment_table_rows)
        self.table_rows_decrement_btn.clicked.connect(self._pending_decrement_table_rows)
        self.auto_clean_btn.clicked.connect(self._pending_toggle_auto_clean)

        self.btn_cd1_from_minus.clicked.connect(lambda: self._adjust_cd('launch_from', -1))
        self.btn_cd1_from_plus.clicked.connect(lambda: self._adjust_cd('launch_from', 1))
        self.btn_cd1_to_minus.clicked.connect(lambda: self._adjust_cd('launch_to', -1))
        self.btn_cd1_to_plus.clicked.connect(lambda: self._adjust_cd('launch_to', 1))
        self.btn_cd2_from_minus.clicked.connect(lambda: self._adjust_cd('finish_from', -1))
        self.btn_cd2_from_plus.clicked.connect(lambda: self._adjust_cd('finish_from', 1))
        self.btn_cd2_to_minus.clicked.connect(lambda: self._adjust_cd('finish_to', -1))
        self.btn_cd2_to_plus.clicked.connect(lambda: self._adjust_cd('finish_to', 1))
        self.btn_cd3_from_minus.clicked.connect(lambda: self._adjust_cd('slot_from', -5))
        self.btn_cd3_from_plus.clicked.connect(lambda: self._adjust_cd('slot_from', 5))
        self.btn_cd3_to_minus.clicked.connect(lambda: self._adjust_cd('slot_to', -5))
        self.btn_cd3_to_plus.clicked.connect(lambda: self._adjust_cd('slot_to', 5))

        # Навигация по разделам
        self.btn_left_general.clicked.connect(lambda: self._set_section(0))
        self.btn_left_boost.clicked.connect(lambda: self._set_section(1))
        self.btn_left_table.clicked.connect(lambda: self._set_section(2))
        self.btn_left_pro.clicked.connect(lambda: self._set_section(3))
        self.btn_left_stats.clicked.connect(lambda: self._set_section(4))
        self._set_section(0)

        self._refresh_cd_labels()
        self._update_configs_list()
        self._add_all_games_add_idx = 0
        self._add_all_task = None
        self._runtime_available = True
        self._runtime_message = ''
        self._thread_pool = QThreadPool.globalInstance()
        self.update_time_label()

    # -------------------- Публичное заполнение значений --------------------
    def set_values_from_config(self, games, time, unlock, fast_copy, time_mode):
        self._pending_games_value = games
        MIN_TIME_SECONDS = 30
        if time < MIN_TIME_SECONDS:
            time = MIN_TIME_SECONDS
        self._pending_time_value = time
        self._pending_unlock_achievements = unlock
        self._pending_fast_copy = fast_copy
        self._pending_time_mode = time_mode

        self.games_value_label.setText(str(games))
        # выставляем индекс времени ближний к self._pending_time_value
        label = self._format_time_label(time)
        if label in self.time_options:
            self.current_time_index = self.time_options.index(label)
        else:
            self.current_time_index = 0
        self.time_value_label.setText(self.time_options[self.current_time_index])
        self.unlock_achievements_btn.setChecked(unlock)
        self.btn_fast_copy_toggle.setChecked(fast_copy)
        self.update_time_label()

    def set_extra_values_from_config(self, config):
        self._pending_loop_boost = config.get('loop_boost', False)
        self.loop_boost_btn.setChecked(self._pending_loop_boost)
        self._pending_table_rows = config.get('table_visible_rows', 15)
        self.table_rows_value_label.setText(str(self._pending_table_rows))
        self._pending_auto_clean_table = config.get('auto_clean_table', False)
        self.auto_clean_btn.setChecked(self._pending_auto_clean_table)
        self._pending_launch_cd_from = config.get('launch_cd_from', 5)
        self._pending_launch_cd_to = config.get('launch_cd_to', 35)
        self._pending_finish_cd_from = config.get('finish_cd_from', 5)
        self._pending_finish_cd_to = config.get('finish_cd_to', 35)
        self._pending_slot_cd_from = config.get('slot_cd_from', 60)
        self._pending_slot_cd_to = config.get('slot_cd_to', 90)
        self._normalize_cd_ranges()
        self._refresh_cd_labels()

    # -------------------- Автосохранение настроек --------------------
    def _emit_current_settings(self):
        MIN_TIME_SECONDS = 30
        time_to_save = int(self._pending_time_value)
        if time_to_save < MIN_TIME_SECONDS:
            time_to_save = MIN_TIME_SECONDS
        self.settings_changed.emit(
            self._pending_games_value,
            time_to_save,
            self._pending_unlock_achievements,
            self._pending_fast_copy,
            self._pending_time_mode,
        )

    def _extra_settings_dict(self):
        self._normalize_cd_ranges()
        return {
            'loop_boost': self._pending_loop_boost,
            'table_visible_rows': self._pending_table_rows,
            'auto_clean_table': self._pending_auto_clean_table,
            'launch_cd_from': self._pending_launch_cd_from,
            'launch_cd_to': self._pending_launch_cd_to,
            'finish_cd_from': self._pending_finish_cd_from,
            'finish_cd_to': self._pending_finish_cd_to,
            'slot_cd_from': self._pending_slot_cd_from,
            'slot_cd_to': self._pending_slot_cd_to,
        }

    def _save_extra_settings(self):
        config = load_config()
        config.update(self._extra_settings_dict())
        save_config(config)
        main_window = self.window()
        if hasattr(main_window, 'config'):
            main_window.config.update(config)
            main_window.loop_boost = self._pending_loop_boost
            main_window.launch_cd_range = (self._pending_launch_cd_from, self._pending_launch_cd_to)
            main_window.finish_cd_range = (self._pending_finish_cd_from, self._pending_finish_cd_to)
            main_window.slot_cd_range = (self._pending_slot_cd_from, self._pending_slot_cd_to)
            if hasattr(main_window, 'main_screen'):
                main_window.main_screen.visible_rows = self._pending_table_rows
                main_window.main_screen.update_game_list()

    def _normalize_cd_ranges(self):
        if self._pending_launch_cd_from > self._pending_launch_cd_to:
            self._pending_launch_cd_to = self._pending_launch_cd_from
        if self._pending_finish_cd_from > self._pending_finish_cd_to:
            self._pending_finish_cd_to = self._pending_finish_cd_from
        if self._pending_slot_cd_from > self._pending_slot_cd_to:
            self._pending_slot_cd_to = self._pending_slot_cd_from

    # -------------------- Обработчики Boost-страницы --------------------
    def _pending_increment_games(self):
        if self._pending_games_value < 60:
            self._pending_games_value += 1
            self.games_value_label.setText(str(self._pending_games_value))
            self.update_time_label()
            self._emit_current_settings()

    def _pending_decrement_games(self):
        if self._pending_games_value > 1:
            self._pending_games_value -= 1
            self.games_value_label.setText(str(self._pending_games_value))
            self.update_time_label()
            self._emit_current_settings()

    def _pending_increment_time(self):
        if self.current_time_index < len(self.time_options) - 1:
            self.current_time_index += 1
            self.time_value_label.setText(self.time_options[self.current_time_index])
            self._pending_time_value = self._parse_time_label(self.time_options[self.current_time_index])
            self.update_time_label()
            self._emit_current_settings()

    def _pending_decrement_time(self):
        if self.current_time_index > 0:
            self.current_time_index -= 1
            self.time_value_label.setText(self.time_options[self.current_time_index])
            self._pending_time_value = self._parse_time_label(self.time_options[self.current_time_index])
            self.update_time_label()
            self._emit_current_settings()

    def _pending_toggle_unlock(self):
        self._pending_unlock_achievements = self.unlock_achievements_btn.isChecked()
        self._emit_current_settings()

    def _pending_toggle_loop(self):
        enabled = self.loop_boost_btn.isChecked()
        if enabled:
            confirm = CustomConfirmDialog(
                self,
                'Зацикленный режим будет повторно запускать сессии до ручной остановки. Включить?',
                'Включить',
                'Отмена',
            )
            if confirm.exec() != QDialog.DialogCode.Accepted:
                self.loop_boost_btn.setChecked(False)
                return
        self._pending_loop_boost = enabled
        self._save_extra_settings()

    def _pending_toggle_fast_copy(self):
        self._pending_fast_copy = self.btn_fast_copy_toggle.isChecked()
        self._emit_current_settings()

    # -------------------- Таблица --------------------
    def _pending_increment_table_rows(self):
        if self._pending_table_rows < 50:
            self._pending_table_rows += 1
            self.table_rows_value_label.setText(str(self._pending_table_rows))
            self._save_extra_settings()

    def _pending_decrement_table_rows(self):
        if self._pending_table_rows > 5:
            self._pending_table_rows -= 1
            self.table_rows_value_label.setText(str(self._pending_table_rows))
            self._save_extra_settings()

    def _pending_toggle_auto_clean(self):
        enabled = self.auto_clean_btn.isChecked()
        if enabled:
            confirm = CustomConfirmDialog(
                self,
                'После завершения буста список игр будет автоматически очищен. Включить?',
                'Включить',
                'Отмена',
            )
            if confirm.exec() != QDialog.DialogCode.Accepted:
                self.auto_clean_btn.setChecked(False)
                return
        self._pending_auto_clean_table = enabled
        self._save_extra_settings()

    def _clear_table(self):
        mw = self.window()
        if getattr(getattr(mw, 'main_screen', None), 'is_boosting', False):
            InfoDialog(self, 'Нельзя очищать таблицу во время буста. Сначала остановите сессию.').exec()
            return
        confirm = CustomConfirmDialog(
            self,
            'Удалить все игры из таблицы? Это действие нельзя отменить.',
            'Удалить',
            'Отмена',
        )
        if confirm.exec() != QDialog.DialogCode.Accepted:
            return
        save_games([])
        if hasattr(mw, 'main_screen'):
            mw.main_screen.games = []
            mw.main_screen.update_game_list()
            mw.main_screen.update_time_label()
            mw.main_screen.set_boost_controls(False)
        InfoDialog(self, 'Таблица очищена.').exec()

    # -------------------- Профессиональное (диапазоны КД) --------------------
    def _adjust_cd(self, kind: str, delta: int):
        if kind == 'launch_from':
            self._pending_launch_cd_from = max(1, min(59, self._pending_launch_cd_from + delta))
        elif kind == 'launch_to':
            self._pending_launch_cd_to = max(2, min(120, self._pending_launch_cd_to + delta))
        elif kind == 'finish_from':
            self._pending_finish_cd_from = max(1, min(59, self._pending_finish_cd_from + delta))
        elif kind == 'finish_to':
            self._pending_finish_cd_to = max(2, min(120, self._pending_finish_cd_to + delta))
        elif kind == 'slot_from':
            self._pending_slot_cd_from = max(5, min(300, self._pending_slot_cd_from + delta))
        elif kind == 'slot_to':
            self._pending_slot_cd_to = max(10, min(600, self._pending_slot_cd_to + delta))
        self._normalize_cd_ranges()
        self._refresh_cd_labels()
        self._save_extra_settings()

    def _refresh_cd_labels(self):
        self.cd1_from_label.setText(f"от {self._pending_launch_cd_from}с.")
        self.cd1_to_label.setText(f"до {self._pending_launch_cd_to}с.")
        self.cd2_from_label.setText(f"от {self._pending_finish_cd_from}с.")
        self.cd2_to_label.setText(f"до {self._pending_finish_cd_to}с.")
        self.cd3_from_label.setText(f"от {self._pending_slot_cd_from}с.")
        self.cd3_to_label.setText(f"до {self._pending_slot_cd_to}с.")

    # -------------------- Вспомогательное --------------------
    def _set_section(self, index: int):
        if not 0 <= index < self.right_stack.count():
            return
        self.right_stack.setCurrentIndex(index)
        if index < len(self._section_buttons):
            self._section_buttons[index].setChecked(True)
        if index == 4:
            self._refresh_statistics()

    def _refresh_statistics(self):
        main_screen = getattr(self.window(), 'main_screen', None)
        games = main_screen.games if main_screen is not None else load_games()
        self.statistics_panel.set_data(games, load_statistics())

    def _reset_statistics(self):
        dialog = CustomConfirmDialog(
            self,
            'Сбросить всю накопленную статистику сеансов? Список игр и настройки не изменятся.',
            'Сбросить',
            'Отмена',
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            reset_statistics()
        except OSError as error:
            InfoDialog(self, f'Не удалось сбросить статистику: {error}').exec()
            return
        self._refresh_statistics()
        InfoDialog(self, 'Статистика сброшена. Игры и настройки сохранены.').exec()

    def _format_time_label(self, seconds):
        seconds = int(seconds)
        if seconds < 60:
            return f"{seconds}с."
        elif seconds < 3600:
            return f"{seconds//60}м."
        elif seconds < 86400:
            return f"{seconds//3600}ч."
        elif seconds <= 604800:
            return f"{seconds//86400}д."
        else:
            return "7д."  # сетка time_options ограничена 7 днями

    def _parse_time_label(self, label):
        if label.endswith('с.'):
            return int(label[:-2])
        elif label.endswith('м.'):
            return int(label[:-2]) * 60
        elif label.endswith('ч.'):
            return int(label[:-2]) * 3600
        elif label.endswith('д.'):
            return int(label[:-2]) * 86400
        elif label.endswith(' нед'):
            return int(label[:-4]) * 604800
        else:
            try:
                return int(label)
            except Exception:
                return 30

    def update_time_label(self):
        main_window = self.window()
        main_screen = getattr(main_window, 'main_screen', None)
        count = len(getattr(main_screen, 'games', [])) if main_screen is not None else 0
        batch = self._pending_games_value
        duration = self._pending_time_value
        time_mode = self._pending_time_mode
        if batch <= 0:
            batch = 1
        MIN_TIME_SECONDS = 30
        if duration < MIN_TIME_SECONDS:
            duration = MIN_TIME_SECONDS
        num_batches = (count + batch - 1) // batch
        total_seconds = num_batches * duration
        if count == 0:
            text = "Добавьте игры для буста."
        else:
            if time_mode == 0:
                text = f"Потребуется {format_time_verbose(total_seconds)}"
            else:
                text = f"Потребуется {format_time_verbose(duration)}"
        self.progress_bar.setFormat(text)
        self.progress_bar.setTextVisible(True)

    def _on_clear_cache(self):
        upload_dir = Path(UPLOAD_DIR)
        removed = []
        for name in ['games_upload.json']:
            p = upload_dir / name
            if p.exists():
                try:
                    p.unlink()
                    removed.append(name)
                except Exception:
                    pass
        main_screen = getattr(self.window(), 'main_screen', None)
        lookup = getattr(main_screen, 'app_lookup', None)
        if lookup is not None:
            lookup.apps = []
            rebuild_index = getattr(lookup, '_rebuild_index', None)
            if callable(rebuild_index):
                rebuild_index()
        if removed:
            InfoDialog(self, f"Удалено: {', '.join(removed)}").exec()
        else:
            InfoDialog(self, "Кэш уже пуст.").exec()

    # --------- Управление конфигами ---------
    def _configs_dir(self) -> Path:
        d = Path(UPLOAD_DIR) / 'configs'
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _update_configs_list(self):
        d = self._configs_dir()
        self._configs = sorted([f for f in d.glob('*.json')])
        self._cfg_index = min(getattr(self, '_cfg_index', 0), max(0, len(self._configs)-1))
        self._update_cfg_label()

    def _update_cfg_label(self):
        if self._configs:
            self.lbl_cfg_name.setText(self._configs[self._cfg_index].name)
        else:
            self.lbl_cfg_name.setText("Нет сохранённых конфигов")

    def _switch_config(self, direction: int):
        if not self._configs:
            self._update_configs_list()
            return
        self._cfg_index = (self._cfg_index + direction) % len(self._configs)
        self._update_cfg_label()

    def _save_new_config(self):
        data = normalize_config({
            'concurrent_value': self._pending_games_value,
            'duration_value': int(self._pending_time_value),
            'unlock_achievements': self._pending_unlock_achievements,
            'fast_paste_enabled': self._pending_fast_copy,
            'time_mode': self._pending_time_mode,
            'loop_boost': self._pending_loop_boost,
            'table_visible_rows': self._pending_table_rows,
            'auto_clean_table': self._pending_auto_clean_table,
            'launch_cd_from': self._pending_launch_cd_from,
            'launch_cd_to': self._pending_launch_cd_to,
            'finish_cd_from': self._pending_finish_cd_from,
            'finish_cd_to': self._pending_finish_cd_to,
            'slot_cd_from': self._pending_slot_cd_from,
            'slot_cd_to': self._pending_slot_cd_to,
        })
        d = self._configs_dir()
        ts = time.strftime('%Y%m%d_%H%M%S')
        path = d / f'config_{ts}_{time.time_ns() % 1_000_000:06d}.json'
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        self._update_configs_list()
        InfoDialog(self, f"Сохранено: {path.name}").exec()

    def _load_selected_config(self):
        if not self._configs:
            self._update_configs_list()
            return
        path = self._configs[self._cfg_index]
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = normalize_config(json.load(f))
        except Exception as e:
            InfoDialog(self, f"Ошибка загрузки: {e}").exec()
            return
        # Заполняем значения и шлём сигнал автосохранения
        self.set_values_from_config(
            data.get('concurrent_value', DEFAULT_CONFIG['concurrent_value']),
            data.get('duration_value', DEFAULT_CONFIG['duration_value']),
            data.get('unlock_achievements', DEFAULT_CONFIG['unlock_achievements']),
            data.get('fast_paste_enabled', DEFAULT_CONFIG['fast_paste_enabled']),
            data.get('time_mode', DEFAULT_CONFIG['time_mode']),
        )
        # Дополнительные
        self._pending_loop_boost = data.get('loop_boost', False)
        self.loop_boost_btn.setChecked(self._pending_loop_boost)
        self._pending_table_rows = data.get('table_visible_rows', 15)
        self.table_rows_value_label.setText(str(self._pending_table_rows))
        self._pending_auto_clean_table = data.get('auto_clean_table', False)
        self.auto_clean_btn.setChecked(self._pending_auto_clean_table)
        self._pending_launch_cd_from = data.get('launch_cd_from', 5)
        self._pending_launch_cd_to = data.get('launch_cd_to', 35)
        self._pending_finish_cd_from = data.get('finish_cd_from', 5)
        self._pending_finish_cd_to = data.get('finish_cd_to', 35)
        self._pending_slot_cd_from = data.get('slot_cd_from', 60)
        self._pending_slot_cd_to = data.get('slot_cd_to', 90)
        self._normalize_cd_ranges()
        self._refresh_cd_labels()
        self._emit_current_settings()
        self._save_extra_settings()
        InfoDialog(self, f"Загружено: {path.name}").exec()

    # -------------------- Добавление всех игр --------------------
    def _on_add_all_games(self):
        if self._add_all_task is not None:
            self._add_all_task.cancel()
            self.btn_add_all_games.setText('Отмена...')
            self.btn_add_all_games.setEnabled(False)
            return
        if not self._runtime_available:
            InfoDialog(self, self._runtime_message or 'Steam runtime недоступен.').exec()
            return
        dlg = CustomConfirmDialog(self, "Вы действительно хотите добавить все игры, которыми вы владеете? \nЭто может занять несколько минут!", "Да", "Нет")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        main_window = self.window()
        main_screen = getattr(main_window, 'main_screen', None)
        if main_screen is None:
            InfoDialog(self, "Не удалось получить доступ к главному окну!").exec()
            return
        existing_appids = {str(g.get('appid')) for g in main_screen.games if isinstance(g, dict) and g.get('appid')}
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('Загрузка каталога Steam...')
        self.btn_add_all_games.setText('Отменить добавление')
        self._set_background_busy(True)

        def collect_owned(cancel_event, emit_progress):
            lookup = SteamAppLookup(allow_fetch=False)
            if not lookup.ensure_loaded():
                raise RuntimeError('Не удалось загрузить каталог Steam. Проверьте интернет.')
            apps = [app for app in lookup.apps if isinstance(app, dict) and app.get('appid')]
            if not apps:
                raise RuntimeError('Каталог Steam пуст или повреждён.')
            names = {str(app['appid']): str(app.get('name') or app['appid']) for app in apps}
            appids = list(names)
            total = len(appids)
            queued = set(existing_appids)
            owned_to_add = []
            booster = SteamBooster(str(BACKGROUND_WORKER))
            started = time.monotonic()
            try:
                for offset in range(0, total, 200):
                    if cancel_event.is_set():
                        return {'cancelled': True, 'items': []}
                    batch = appids[offset:offset + 200]
                    for appid in booster.check_games_owned_batch(batch):
                        appid = str(appid)
                        if appid not in queued:
                            owned_to_add.append((appid, names.get(appid, appid)))
                            queued.add(appid)
                    checked = min(total, offset + len(batch))
                    elapsed = max(0.001, time.monotonic() - started)
                    speed = checked / elapsed
                    emit_progress({
                        'checked': checked,
                        'total': total,
                        'eta': int((total - checked) / speed) if speed else 0,
                    })
                return {'cancelled': False, 'items': owned_to_add}
            finally:
                booster.shutdown_server()

        task = BackgroundTask(collect_owned)
        task.signals.progress.connect(self._on_add_all_progress)
        task.signals.result.connect(self._on_add_all_result)
        task.signals.error.connect(self._on_add_all_error)
        task.signals.finished.connect(self._on_add_all_finished)
        self._add_all_task = task
        self._thread_pool.start(task)

    def _on_add_all_progress(self, progress):
        checked = int(progress.get('checked', 0))
        total = max(1, int(progress.get('total', 1)))
        percent = max(0, min(100, int(100 * checked / total)))
        self.progress_bar.setValue(percent)
        self.progress_bar.setFormat(
            f"Проверка игр: {percent}% | {checked}/{total} | Осталось: {self._format_eta(int(progress.get('eta', 0)))}"
        )

    def _on_add_all_result(self, result):
        if not isinstance(result, dict):
            return
        if result.get('cancelled'):
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat('Добавление отменено пользователем.')
            return
        main_screen = getattr(self.window(), 'main_screen', None)
        if main_screen is None:
            self._on_add_all_error('Главный экран был закрыт до завершения операции.')
            return
        items = result.get('items') or []
        added = main_screen.add_games_bulk(items)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat(f'Готово. Добавлено игр: {added}.')
        InfoDialog(self, f'Добавлено игр: {added}. Дубликаты автоматически пропущены.').exec()

    def _on_add_all_error(self, message):
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat('Операция завершилась с ошибкой.')
        InfoDialog(self, f'Не удалось добавить игры: {message}').exec()

    def _on_add_all_finished(self):
        self._add_all_task = None
        self._set_background_busy(False)
        self.btn_add_all_games.setText('Добавить все игры')
        self.btn_add_all_games.setEnabled(self._runtime_available)

    def _set_background_busy(self, busy):
        for button in self.findChildren(QPushButton):
            if button is not self.btn_add_all_games:
                button.setEnabled(not busy)
        self.btn_add_all_games.setEnabled(True)

    def cancel_background_operations(self):
        if self._add_all_task is not None:
            self._add_all_task.cancel()

    def set_runtime_available(self, available, message=''):
        self._runtime_available = bool(available)
        self._runtime_message = str(message or '')
        if self._add_all_task is None:
            self.btn_add_all_games.setEnabled(self._runtime_available)

    def _extract_steam_apps(self, data):
        if isinstance(data, dict):
            apps = data.get('applist', {}).get('apps', [])
        elif isinstance(data, list):
            apps = data
        else:
            apps = []

        normalized = []
        seen = set()
        for app in apps:
            if not isinstance(app, dict) or 'appid' not in app:
                continue
            try:
                appid = int(app.get('appid'))
            except (TypeError, ValueError):
                continue
            if appid <= 0 or appid in seen:
                continue
            seen.add(appid)
            normalized.append({
                'appid': appid,
                'name': str(app.get('name') or appid),
            })
        return normalized

    def _format_eta(self, eta_sec: int) -> str:
        if eta_sec > 604800:
            return f"~{eta_sec//604800} нед {(eta_sec%604800)//86400} д"
        if eta_sec > 86400:
            return f"~{eta_sec//86400} д {(eta_sec%86400)//3600}ч"
        if eta_sec > 3600:
            return f"~{eta_sec//3600}ч {eta_sec%3600//60}м"
        if eta_sec > 60:
            return f"~{eta_sec//60}м {eta_sec%60}с"
        return f"~{eta_sec}с"

    # -------------------- Навигация
    def _on_back_clicked(self):
        # При возврате сбрасываем правую панель на первую страницу
        self._set_section(0)
        # Обновим значения из главного окна
        main_window = self.window()
        if main_window:
            games = getattr(main_window, 'concurrent_value', DEFAULT_CONFIG['concurrent_value'])
            time_val = getattr(main_window, 'duration_value', DEFAULT_CONFIG['duration_value'])
            unlock = getattr(main_window, 'unlock_achievements', DEFAULT_CONFIG['unlock_achievements'])
            fast_copy = getattr(main_window, 'fast_paste_enabled', DEFAULT_CONFIG['fast_paste_enabled'])
            time_mode = getattr(main_window, 'time_mode', DEFAULT_CONFIG['time_mode'])
            self.set_values_from_config(games, time_val, unlock, fast_copy, time_mode)
        self.back_requested.emit()

__all__ = ['SettingsScreenWidget']
