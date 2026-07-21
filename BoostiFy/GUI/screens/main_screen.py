# main_screen.py — главный экран приложения

from PyQt6.QtWidgets import QWidget, QPushButton, QProgressBar, QTableView, QDialog
from PyQt6.QtCore import pyqtSignal, QTimer, Qt, QItemSelectionModel, QItemSelection, QThreadPool
from PyQt6.QtGui import QGuiApplication
from BoostiFy.GUI.widgets.editable_label import EditableLabel
from BoostiFy.GUI.utils.styles import BUTTON_STYLE
from BoostiFy.GUI.utils.helpers import format_time_verbose
from BoostiFy.GUI.core.game_storage import DEFAULT_CONFIG, load_games, save_games
from BoostiFy.core.booster import SteamBooster
from BoostiFy.core.steam_lookup import SteamAppLookup
from BoostiFy.GUI.widgets.toast import CustomConfirmDialog, InfoDialog
from BoostiFy.GUI.screens.table_widget import GameTableModel
from BoostiFy.core.runtime_paths import BACKGROUND_WORKER
from BoostiFy.GUI.core.async_tasks import BackgroundTask

__all__ = ['MainScreenWidget']

class MainScreenWidget(QWidget):
    settings_requested = pyqtSignal()
    add_game_requested = pyqtSignal(str)
    del_game_requested = pyqtSignal()
    start_boost_requested = pyqtSignal()
    stop_boost_requested = pyqtSignal()
    toast_signal = pyqtSignal(str, int)
    update_progress_signal = pyqtSignal(object) 
    set_game_status_signal = pyqtSignal(str, str)
    force_table_update_signal = pyqtSignal()
    boost_finished_signal = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: transparent;")
        self.games = load_games()
        self.selected_rows = set()
        self.last_clicked_row = None
        self.filter_text = ""
        self.sort_column = None
        self.sort_reverse = False
        self.scroll_offset = 0
        self.row_height = 30
        self.header_height = 32
        self.visible_rows = 13
        self._runtime_available = True
        self._runtime_message = ""
        self._add_in_progress = False
        self._add_task = None
        self._thread_pool = QThreadPool.globalInstance()
        self.max_scroll = 0
        # --- ЛОГОТИП НАД ПОИСКОМ ---
        # Локальный логотип в этой области больше не нужен, т.к. верхний логотип в main_window перекрывает титл-бар и доходит до поиска
        # Блок оставлен на случай будущей кастомизации

        # --- Ручное позиционирование элементов ---
        self.editable_label = EditableLabel("AppID / Название игры", self)
        self.editable_label.setGeometry(30, 45, 280, 45)
        self.editable_label.setStyleSheet("""
            QLabel, QLineEdit {
                background-color: #232b36;
                color: #e6e6e6;
                border: 2px solid #1A9AF3;
                border-radius: 10px;
                font-size: 18px;
                padding: 8px 12px;
            }
            QLineEdit:focus {
                border: 2px solid #4FC3F7;
                background-color: #263142;
            }
            QLabel {
                color: #888;
            }
        """)
        self.editable_label.enter_pressed.connect(self._handle_enter_pressed)
        self.editable_label.text_changed.connect(self._handle_filter_changed)
        self.btn_add_game = QPushButton("Добавить игру", self)
        self.btn_add_game.setGeometry(30, 120, 280, 45)
        self.btn_add_game.setStyleSheet(BUTTON_STYLE)
        self.btn_add_game.clicked.connect(lambda _: self._emit_add_game())
        self.btn_del_game = QPushButton("Удалить выбранное", self)
        self.btn_del_game.setGeometry(30, 195, 280, 45)
        self.btn_del_game.setStyleSheet(BUTTON_STYLE)
        self.btn_del_game.clicked.connect(self._emit_del_game)
        self.btn_start_boost = QPushButton("Запустить буст", self)
        self.btn_start_boost.setGeometry(30, 270, 280, 45)
        self.btn_start_boost.setStyleSheet(BUTTON_STYLE)
        self.btn_start_boost.clicked.connect(self.start_boost_requested.emit)
        self.btn_stop_boost = QPushButton("Остановить", self)
        self.btn_stop_boost.setGeometry(30, 345, 280, 45)
        self.btn_stop_boost.setStyleSheet(BUTTON_STYLE)
        self.btn_stop_boost.clicked.connect(self.stop_boost_requested.emit)
        self.btn_settings = QPushButton("Настройки", self)
        self.btn_settings.setGeometry(30, 420, 280, 45)
        self.btn_settings.setStyleSheet(BUTTON_STYLE)
        self.btn_settings.clicked.connect(self.settings_requested.emit)
        self.game_table_model = GameTableModel(self.games)
        self.game_table = QTableView(self)
        self.game_table.setModel(self.game_table_model)
        self.game_table.setGeometry(340, 45, 590, 420)
        self.game_table.setStyleSheet('''
            QTableView {
                background-color: #232b36;
                color: #e6e6e6;
                border: none;
                border-radius: 16px;
                font-size: 18px;
                padding: 8px;
            }
        ''')
        self.game_table.horizontalHeader().setStretchLastSection(True)
        self.game_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.game_table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.game_table.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.game_table.verticalHeader().setVisible(False)
        self.game_table.selectionModel().selectionChanged.connect(self._handle_table_selection_changed)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setGeometry(30, 495, 900, 30)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #2b3541;
                color: #dcdedf;
                border: none;
                border-radius: 10px;
                text-align: center;
                font-size: 18px;
            }
            QProgressBar::chunk {
                background-color: #1A9AF3;
                margin: 0px;
            }
            QProgressBar::chunk:horizontal {
                border-top-left-radius: 10px;
                border-bottom-left-radius: 10px;
                border-top-right-radius: 10px;
                border-bottom-right-radius: 10px;
            }
        """)
        self.progress_bar.setMinimum(0)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.installEventFilter(self)
        self.game_table.installEventFilter(self)
        self.update_progress_signal.connect(self._update_progress_bar_slot)
        self.set_game_status_signal.connect(self._set_game_status_slot)
        self.force_table_update_signal.connect(self._force_table_update_slot)
        self.boost_finished_signal.connect(self.reset_progress_bar)
        self._table_update_pending = False  # Флаг для защиты от частых обновлений
        self.update_game_list()
        QTimer.singleShot(200, lambda: self.force_table_update())
        self.app_lookup = SteamAppLookup(allow_fetch=False)
        self.booster = SteamBooster(str(BACKGROUND_WORKER))
        self.is_boosting = False
        self.set_boost_controls(False)

    def _emit_add_game(self, text=None):
        if text is None:
            if self.editable_label.edit.isVisible():
                text = self.editable_label.edit.text().strip()
            else:
                text = self.editable_label.label.text().strip()
        if not isinstance(text, str):
            text = str(text)
        if text and text != self.editable_label.placeholder and text != "False":
            self.add_game_requested.emit(text)
    def _handle_enter_pressed(self, text):
        self._emit_add_game(text)
    def _handle_filter_changed(self, text):
        self.filter_text = text.strip()
        self.update_game_list()
    def _emit_del_game(self):
        self.del_game_requested.emit()
    def add_game(self, appid, name=None, status="Ожидание"):
        if self.is_boosting:
            return False
        appid = str(appid)
        if any(str(game.get('appid')) == appid for game in self.games if isinstance(game, dict)):
            return False
        self.games.append({'appid': appid, 'name': str(name or appid), 'status': str(status)})
        save_games(self.games)
        self.filter_text = ''
        self.editable_label.edit.clear()
        self.editable_label.label.setText(self.editable_label.placeholder)
        self.update_game_list()
        self.update_time_label()
        self.set_boost_controls(False)
        QTimer.singleShot(100, lambda: self.force_table_update())
        return True

    def add_games_bulk(self, items):
        """Добавляет несколько игр за один проход: одна запись на диск и одно обновление
        таблицы вместо N (важно для «Добавить все игры»). Возвращает количество добавленных."""
        if self.is_boosting:
            return 0
        added = 0
        existing = {str(game.get('appid')) for game in self.games if isinstance(game, dict)}
        for appid, name in items:
            appid = str(appid)
            if not appid.isdigit() or appid in existing:
                continue
            self.games.append({'appid': appid, 'name': str(name or appid), 'status': 'Ожидание'})
            existing.add(appid)
            added += 1
        if added:
            save_games(self.games)
            self.filter_text = ''
            self.editable_label.edit.clear()
            self.editable_label.label.setText(self.editable_label.placeholder)
            self.update_game_list()
            self.update_time_label()
            self.set_boost_controls(False)
            QTimer.singleShot(100, lambda: self.force_table_update())
        return added
    def remove_selected_game(self):
        if self.is_boosting or self._add_in_progress:
            self._reject_add('Список временно заблокирован. Дождитесь проверки или остановите сессию.')
            return
        self._sync_selected_rows_from_table()
        if self.selected_rows:
            count = len(self.selected_rows)
            confirm = CustomConfirmDialog(
                self,
                f'Удалить выбранные игры ({count})? Это действие нельзя отменить.',
                'Удалить',
                'Отмена',
            )
            if confirm.exec() != QDialog.DialogCode.Accepted:
                return
            for row in sorted(self.selected_rows, reverse=True):
                if 0 <= row < len(self.games):
                    self.games.pop(row)
            self.selected_rows.clear()
            save_games(self.games)
            self.update_game_list()
            self.update_time_label()
            self.set_boost_controls(False)
            QTimer.singleShot(100, lambda: self.force_table_update())
        else:
            InfoDialog(self, 'Ни одна игра не выбрана для удаления!').exec()
    def update_game_list(self):
        if not hasattr(self, 'game_table') or not self.game_table:
            return
        self.game_table.show()
        if self.filter_text:
            filter_lower = self.filter_text.lower()
            self.filtered_games = [
                g for g in self.games
                if filter_lower in str(g.get('appid', '')).lower()
                or filter_lower in str(g.get('name', '')).lower()
            ]
        else:
            self.filtered_games = self.games[:]
        if self.sort_column:
            if self.sort_column == 'num':
                if self.sort_reverse:
                    self.filtered_games = list(reversed(self.filtered_games))
            elif self.sort_column == 'appid':
                def appid_sort_key(game):
                    try:
                        return int(game.get('appid', 0))
                    except (TypeError, ValueError):
                        return 0
                self.filtered_games = sorted(self.filtered_games, key=appid_sort_key, reverse=self.sort_reverse)
            elif self.sort_column == 'name':
                self.filtered_games = sorted(self.filtered_games, key=lambda g: str(g.get('name', '')).lower(), reverse=self.sort_reverse)
            elif self.sort_column == 'status':
                self.filtered_games = sorted(self.filtered_games, key=lambda g: str(g.get('status', '')).lower(), reverse=self.sort_reverse)
        self.game_table_model.set_games(self.filtered_games)
        # Фиксируем ширину столбцов после обновления данных
        self.game_table.setColumnWidth(0, 60)
        self.game_table.setColumnWidth(1, 90)
        self.game_table.setColumnWidth(2, 290)
        self.game_table.setColumnWidth(3, 105)
        self.update_row_highlight()
        if not getattr(self, 'is_boosting', False):
            self.update_time_label()
        # Защита от частых обновлений: только если не запланировано
        if not self._table_update_pending:
            self._table_update_pending = True
            QTimer.singleShot(200, self._reset_table_update_pending_and_force_update)

    def _reset_table_update_pending_and_force_update(self):
        self._table_update_pending = False
        self.force_table_update()

    def force_table_update(self):
        self.force_table_update_signal.emit()
    def _force_table_update_slot(self):
        if hasattr(self, 'game_table') and self.game_table:
            self.game_table.update()
            self.game_table.repaint()
            self.game_table.show()
            self.update()
            self.repaint()
    def set_game_status(self, appid, status):
        self.set_game_status_signal.emit(str(appid), str(status))

    def _set_game_status_slot(self, appid, status):
        status = self._display_status(status)
        for game in self.games:
            if isinstance(game, dict) and str(game.get('appid')) == str(appid):
                game['status'] = status
                break
        else:
            return
        # Статусы во время буста транзиентные: сохраняем их одним проходом при завершении.
        self.game_table_model.layoutChanged.emit()
        self.force_table_update_signal.emit()

    @staticmethod
    def _display_status(status):
        value = str(status or '').strip()
        translations = {
            'started': 'Бустится',
            'done': 'Готово',
            'stopped': 'Остановлено',
            'skipped: black list': 'Пропущено: чёрный список',
        }
        if value in translations:
            return translations[value]
        if value.startswith('error:'):
            detail = value.split(':', 1)[1].strip()
            return f"Ошибка: {detail}"[:500]
        return value[:500] or 'Ожидание'

    def set_all_status(self, status):
        """Ставит статус всем играм разом: один проход по памяти + одно сохранение + одна
        перерисовка вместо N (иначе O(n) записей файла и перерисовок на GUI-потоке)."""
        for g in self.games:
            g['status'] = status
        save_games(self.games)
        self.game_table_model.layoutChanged.emit()
        self.force_table_update_signal.emit()

    def finalize_session_statuses(self, stopped=False):
        terminal_prefixes = ('Готово', 'Ошибка:', 'Пропущено:', 'Остановлено')
        fallback = 'Остановлено' if stopped else 'Не выполнено'
        for game in self.games:
            status = str(game.get('status', ''))
            if not status.startswith(terminal_prefixes):
                game['status'] = fallback
        save_games(self.games)
        self.game_table_model.layoutChanged.emit()
        self.force_table_update_signal.emit()

    def start_boost(self):
        self.is_boosting = True
        self.set_all_status('Бустится')
    def stop_boost(self):
        self.is_boosting = False
        self.set_all_status('Готово')
        self.update_time_label()
    def _reset_input(self):
        """Возвращает поле ввода и фильтр в исходное состояние (placeholder, пустой фильтр)."""
        self.editable_label.label.setText(self.editable_label.placeholder)
        if self.editable_label.edit.isVisible():
            self.editable_label.edit.clear()
        self.filter_text = ''
        self.update_game_list()

    def _reject_add(self, message):
        """Показывает сообщение об ошибке добавления и сбрасывает ввод."""
        InfoDialog(self, message).exec()
        self._reset_input()

    def try_add_game(self, text):
        text = str(text or '').strip()
        if not text or text == "AppID / Название игры":
            self._reject_add('Введите AppID или название игры')
            return
        if len(text) > 200:
            self._reject_add('Запрос слишком длинный. Введите AppID или точное название до 200 символов.')
            return
        if self._add_in_progress:
            self._reject_add('Предыдущая проверка ещё выполняется. Дождитесь результата.')
            return
        if not self._runtime_available:
            self._reject_add(self._runtime_message or 'Steam runtime недоступен.')
            return
        if text.isdigit() and not (0 < int(text) <= 0xFFFFFFFF):
            self._reject_add('AppID должен быть числом от 1 до 4294967295.')
            return

        existing_appids = {str(game.get('appid')) for game in self.games if isinstance(game, dict)}
        self._set_add_busy(True)

        def resolve_game(cancel_event, _progress):
            if cancel_event.is_set():
                return None
            if text.isdigit():
                appid = str(int(text))
            else:
                if not self.app_lookup.ensure_loaded():
                    raise RuntimeError('Не удалось загрузить каталог Steam. Проверьте интернет и повторите попытку.')
                exact_lookup = getattr(self.app_lookup, 'find_exact_appid', None)
                appid = exact_lookup(text) if callable(exact_lookup) else self.app_lookup.find_appid(text)
                if not appid:
                    similar = self.app_lookup.find_similar(text, limit=3)
                    suggestions = ', '.join(
                        f"{item.get('name')} (AppID {item.get('appid')})" for item in similar
                    )
                    if suggestions:
                        raise ValueError(f'Нужно точное название. Возможно, вы искали: {suggestions}')
                    raise ValueError('Игра с таким точным названием не найдена.')
                appid = str(appid)
            if appid in existing_appids:
                raise ValueError('Эта игра уже есть в списке.')
            if cancel_event.is_set():
                return None
            if not self.booster.check_game_owned(int(appid)):
                raise ValueError('Эта игра не принадлежит вашему аккаунту Steam.')
            return {'appid': appid, 'name': self.get_name_by_appid(appid)}

        task = BackgroundTask(resolve_game)
        task.signals.result.connect(self._on_game_resolved)
        task.signals.error.connect(self._reject_add)
        task.signals.finished.connect(self._on_add_finished)
        self._add_task = task
        self._thread_pool.start(task)

    def _on_game_resolved(self, result):
        if not result:
            return
        appid = str(result.get('appid', ''))
        name = str(result.get('name') or appid)
        if not appid or any(str(game.get('appid')) == appid for game in self.games if isinstance(game, dict)):
            self._reject_add('Игра уже была добавлена, пока выполнялась проверка.')
            return
        self.add_game(appid, name)

    def _on_add_finished(self):
        self._add_task = None
        self._add_in_progress = False
        self.set_boost_controls(self.is_boosting)
        if not self.is_boosting:
            self.update_time_label()

    def _set_add_busy(self, busy):
        self._add_in_progress = bool(busy)
        self.set_boost_controls(self.is_boosting)
        if busy:
            self.progress_bar.setFormat('Проверка игры и владения в Steam...')
        elif not self.is_boosting:
            self.update_time_label()

    def set_runtime_available(self, available, message=''):
        self._runtime_available = bool(available)
        self._runtime_message = str(message or '')
        self.set_boost_controls(self.is_boosting)
        if not available:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat(self._runtime_message or 'Steam runtime не собран.')

    def set_boost_controls(self, active, stopping=False):
        self.is_boosting = bool(active)
        mutable = not active and not self._add_in_progress
        self.btn_add_game.setEnabled(mutable and self._runtime_available)
        self.btn_del_game.setEnabled(mutable)
        self.btn_settings.setEnabled(mutable)
        self.btn_start_boost.setEnabled(mutable and self._runtime_available and bool(self.games))
        self.btn_stop_boost.setEnabled(active and not stopping)
        self.editable_label.setEnabled(mutable and self._runtime_available)
        if stopping:
            self.progress_bar.setFormat('Остановка процессов...')
    def update_time_label(self):
        if getattr(self, 'is_boosting', False):
            return  # Во время буста не трогаем progress_bar
        count = len(self.games)
        window = self.window()
        batch = getattr(window, 'concurrent_value', DEFAULT_CONFIG['concurrent_value'])
        duration = getattr(window, 'duration_value', DEFAULT_CONFIG['duration_value'])
        time_mode = getattr(window, 'time_mode', DEFAULT_CONFIG['time_mode'])
        # Валидация значений
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
    def eventFilter(self, obj, event):
        # Прокрутку колёсиком делает сам QTableView (нативно). Прежний обработчик её блокировал
        # и на каждый тик перестраивал весь список, при этом scroll_offset ни на что не влиял.
        if event.type() == event.Type.KeyPress:
            if self.editable_label.edit.hasFocus():
                return super().eventFilter(obj, event)
            if event.key() == Qt.Key.Key_A and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                source_index = self._source_row_index()
                self.selected_rows = {
                    source_index[appid]
                    for appid in (
                        str(g.get('appid', '')) if isinstance(g, dict) else ''
                        for g in getattr(self, 'filtered_games', [])
                    )
                    if appid in source_index
                }
                self.update_row_highlight()
                event.accept()
                return True
            if event.key() == Qt.Key.Key_V and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                fast_paste = False
                p = self.parent()
                while p is not None:
                    if hasattr(p, 'fast_paste_enabled'):
                        fast_paste = getattr(p, 'fast_paste_enabled', False)
                        break
                    p = p.parent() if hasattr(p, 'parent') else None
                if fast_paste:
                    clipboard = QGuiApplication.clipboard()
                    if clipboard is not None:
                        clipboard_text = clipboard.text().strip()
                        if clipboard_text:
                            self.try_add_game(clipboard_text)
                            self.filter_text = ''
                            self.editable_label.edit.clear()
                            self.editable_label.label.setText(self.editable_label.placeholder)
                            self.update_game_list()
                            QTimer.singleShot(100, lambda: self.force_table_update())
                    event.accept()
                    return True
        return super().eventFilter(obj, event)
    def update_row_highlight(self):
        if not hasattr(self, 'game_table') or not self.game_table:
            return
        selection_model = self.game_table.selectionModel()
        if selection_model is None:
            return
        selection_model.blockSignals(True)
        selection_model.clearSelection()
        source_index = self._source_row_index()
        model = self.game_table_model
        last_col = max(0, model.columnCount() - 1)
        # Копим выделение в один QItemSelection и применяем одним вызовом,
        # а не тысячами отдельных select() (важно для Ctrl+A по большому списку).
        selection = QItemSelection()
        for row, game in enumerate(getattr(self, 'filtered_games', [])):
            appid = str(game.get('appid', '')) if isinstance(game, dict) else ''
            if source_index.get(appid) in self.selected_rows:
                selection.select(model.index(row, 0), model.index(row, last_col))
        if not selection.isEmpty():
            selection_model.select(
                selection,
                QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
            )
        selection_model.blockSignals(False)
        self.game_table.update()

    def _source_row_index(self):
        """{appid: индекс в self.games} (первое вхождение). Строится за O(n) для O(1) поиска
        вместо O(n) на каждый вызов — критично при больших списках игр."""
        index = {}
        for idx, item in enumerate(self.games):
            appid = str(item.get('appid', '')) if isinstance(item, dict) else ''
            if appid and appid not in index:
                index[appid] = idx
        return index

    def _sync_selected_rows_from_table(self):
        if not hasattr(self, 'game_table') or not self.game_table:
            return
        selection_model = self.game_table.selectionModel()
        if selection_model is None:
            return
        selected_rows = set()
        source_index = self._source_row_index()
        for model_index in selection_model.selectedRows():
            game = self.game_table_model.get_game(model_index.row())
            appid = str(game.get('appid', '')) if isinstance(game, dict) else ''
            source_row = source_index.get(appid) if appid else None
            if source_row is not None:
                selected_rows.add(source_row)
        self.selected_rows = selected_rows

    def _handle_table_selection_changed(self, selected, deselected):
        self._sync_selected_rows_from_table()

    def _sort_by(self, column):
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False
        self.update_game_list()

    def update_progress_bar(self, progress_data: dict):
        if not isinstance(progress_data, dict):
            return

        games_done = progress_data.get('games_done', 0)
        games_total = progress_data.get('games_total', 0)
        # --- ПОЛУЧАЕМ ОДНО, ФИНАЛЬНОЕ, УЖЕ РАССЧИТАННОЕ ВРЕМЯ ---
        eta_sec = progress_data.get('final_eta_sec', 0)

        percent = int((games_done / games_total) * 100) if games_total > 0 else 0
        self.progress_bar.setValue(percent)

        eta_str = format_time_verbose(eta_sec) # Ваша функция форматирования
        text = f"Выполнено: {games_done} из {games_total} ({percent}%) | Осталось: {eta_str}"

        self.progress_bar.setFormat(text)
        self.progress_bar.setTextVisible(True)

    # --- СЛОТ ПРОСТО ПЕРЕДАЕТ ДАННЫЕ ДАЛЬШЕ ---
    def _update_progress_bar_slot(self, progress_data):
        self.update_progress_bar(progress_data)

    def get_name_by_appid(self, appid):
        appid_str = str(appid)
        lookup = getattr(self, 'app_lookup', None)
        if lookup is not None:
            get_name = getattr(lookup, 'get_name', None)
            if callable(get_name):  # быстрый путь: O(1) обратный индекс
                name = get_name(appid_str)
                if name:
                    return name
            else:  # fallback (напр. тестовый лукап без индекса)
                for app in getattr(lookup, 'apps', []):
                    if isinstance(app, dict) and str(app.get('appid')) == appid_str:
                        return app.get('name') or appid_str
        return appid_str

    def reset_progress_bar(self):
        save_games(self.games)
        self.set_boost_controls(False)
        self.progress_bar.setValue(0)
        self.update_time_label()
