from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

from BoostiFy.GUI.core.statistics_storage import classify_game_statuses
from BoostiFy.GUI.utils.styles import ACTIVE_COLOR, ELEMENT_BG_COLOR, FONT_FAMILY, TEXT_COLOR


SUCCESS_COLOR = "#41c98d"
ERROR_COLOR = "#ff6b6b"
SKIPPED_COLOR = "#f5b84b"
IDLE_COLOR = "#465362"
CARD_STYLE = f"""
    QFrame#statisticsCard, QFrame#statisticsPanel {{
        background-color: {ELEMENT_BG_COLOR};
        border: none;
        border-radius: 10px;
    }}
"""
SMALL_LABEL_STYLE = f"""
    color: #9eabb8;
    background: transparent;
    font-family: '{FONT_FAMILY}';
    font-size: 12px;
    font-weight: 600;
"""
BODY_LABEL_STYLE = f"""
    color: {TEXT_COLOR};
    background: transparent;
    font-family: '{FONT_FAMILY}';
    font-size: 14px;
"""
ACTION_BUTTON_STYLE = f"""
    QPushButton {{
        color: {TEXT_COLOR};
        background-color: {ELEMENT_BG_COLOR};
        border: none;
        border-radius: 10px;
        font-family: '{FONT_FAMILY}';
        font-size: 15px;
    }}
    QPushButton:hover {{
        color: {ACTIVE_COLOR};
        background-color: #313d4a;
    }}
    QPushButton:pressed {{
        color: white;
        background-color: {ACTIVE_COLOR};
    }}
"""


def _number(value):
    return f"{max(0, int(value or 0)):,}".replace(",", " ")


def _duration(seconds):
    seconds = max(0, int(seconds or 0))
    if seconds < 60:
        return f"{seconds} сек."
    minutes, _ = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} мин."
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours} ч. {minutes} мин." if minutes else f"{hours} ч."
    days, hours = divmod(hours, 24)
    return f"{days} д. {hours} ч." if hours else f"{days} д."


class StatusDistributionBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.counts = (0, 0, 0, 0)

    def set_counts(self, successful, failed, skipped, other):
        self.counts = tuple(max(0, int(value)) for value in (successful, failed, skipped, other))
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(rect.x(), rect.y(), rect.width(), rect.height(), 7, 7)
        painter.fillPath(path, QColor("#202832"))
        total = sum(self.counts)
        if total <= 0:
            return
        painter.setClipPath(path)
        x = 0
        colors = (SUCCESS_COLOR, ERROR_COLOR, SKIPPED_COLOR, IDLE_COLOR)
        last_nonzero = max(index for index, count in enumerate(self.counts) if count > 0)
        for index, (count, color) in enumerate(zip(self.counts, colors, strict=True)):
            if count <= 0:
                continue
            width = self.width() - x if index == last_nonzero else round(self.width() * count / total)
            painter.fillRect(x, 0, max(1, width), self.height(), QColor(color))
            x += width


class StatisticsCard(QFrame):
    def __init__(self, caption, accent=ACTIVE_COLOR, parent=None):
        super().__init__(parent)
        self.setObjectName("statisticsCard")
        self.setStyleSheet(CARD_STYLE)
        self.caption_label = QLabel(caption.upper(), self)
        self.caption_label.setGeometry(12, 8, 116, 18)
        self.caption_label.setStyleSheet(SMALL_LABEL_STYLE)
        self.value_label = QLabel("0", self)
        self.value_label.setGeometry(12, 27, 116, 34)
        self.value_label.setStyleSheet(
            f"color: {accent}; background: transparent; font-family: '{FONT_FAMILY}'; "
            "font-size: 26px; font-weight: 700;"
        )
        self.detail_label = QLabel("—", self)
        self.detail_label.setGeometry(12, 63, 116, 17)
        self.detail_label.setStyleSheet(
            f"color: #9eabb8; background: transparent; font-family: '{FONT_FAMILY}'; font-size: 11px;"
        )

    def set_value(self, value, detail):
        self.value_label.setText(str(value))
        self.detail_label.setText(str(detail))


class StatisticsPanel(QWidget):
    refresh_requested = pyqtSignal()
    reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.snapshot = {}

        self.title_label = QLabel("Обзор активности", self)
        self.title_label.setGeometry(0, 0, 340, 45)
        self.title_label.setStyleSheet(
            f"color: {TEXT_COLOR}; background: transparent; font-family: '{FONT_FAMILY}'; "
            "font-size: 23px; font-weight: 700;"
        )

        self.refresh_button = QPushButton("Обновить", self)
        self.refresh_button.setGeometry(350, 0, 105, 45)
        self.refresh_button.setToolTip("Обновить статистику")
        self.refresh_button.setStyleSheet(ACTION_BUTTON_STYLE)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)

        self.reset_button = QPushButton("Сбросить", self)
        self.reset_button.setGeometry(465, 0, 125, 45)
        self.reset_button.setToolTip("Сбросить накопленную статистику")
        self.reset_button.setStyleSheet(ACTION_BUTTON_STYLE)
        self.reset_button.clicked.connect(self.reset_requested.emit)

        self.library_card = StatisticsCard("Игр в списке", parent=self)
        self.sessions_card = StatisticsCard("Сеансов", parent=self)
        self.success_card = StatisticsCard("Успешно", SUCCESS_COLOR, self)
        self.reliability_card = StatisticsCard("Надёжность", ACTIVE_COLOR, self)
        for index, card in enumerate(
            (self.library_card, self.sessions_card, self.success_card, self.reliability_card)
        ):
            card.setGeometry(index * 150, 60, 140, 88)

        self.library_panel = QFrame(self)
        self.library_panel.setObjectName("statisticsPanel")
        self.library_panel.setGeometry(0, 163, 590, 95)
        self.library_panel.setStyleSheet(CARD_STYLE)
        library_title = QLabel("СОСТОЯНИЕ ТЕКУЩЕЙ ТАБЛИЦЫ", self.library_panel)
        library_title.setGeometry(15, 8, 280, 20)
        library_title.setStyleSheet(SMALL_LABEL_STYLE)
        self.library_summary_label = QLabel("", self.library_panel)
        self.library_summary_label.setGeometry(295, 8, 280, 20)
        self.library_summary_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.library_summary_label.setStyleSheet(SMALL_LABEL_STYLE)
        self.distribution_bar = StatusDistributionBar(self.library_panel)
        self.distribution_bar.setGeometry(15, 37, 560, 15)
        self.legend_label = QLabel("", self.library_panel)
        self.legend_label.setGeometry(15, 61, 560, 23)
        self.legend_label.setTextFormat(Qt.TextFormat.RichText)
        self.legend_label.setStyleSheet(BODY_LABEL_STYLE)

        self.activity_panel = QFrame(self)
        self.activity_panel.setObjectName("statisticsPanel")
        self.activity_panel.setGeometry(0, 273, 590, 105)
        self.activity_panel.setStyleSheet(CARD_STYLE)
        activity_title = QLabel("ПОСЛЕДНИЙ СЕАНС", self.activity_panel)
        activity_title.setGeometry(15, 8, 220, 20)
        activity_title.setStyleSheet(SMALL_LABEL_STYLE)
        self.total_time_label = QLabel("Общее время: 0 сек.", self.activity_panel)
        self.total_time_label.setGeometry(245, 8, 330, 20)
        self.total_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.total_time_label.setStyleSheet(SMALL_LABEL_STYLE)
        self.last_summary_label = QLabel("Сеансов пока не было", self.activity_panel)
        self.last_summary_label.setGeometry(15, 36, 360, 25)
        self.last_summary_label.setStyleSheet(
            f"color: {TEXT_COLOR}; background: transparent; font-family: '{FONT_FAMILY}'; "
            "font-size: 17px; font-weight: 600;"
        )
        self.last_time_label = QLabel("", self.activity_panel)
        self.last_time_label.setGeometry(380, 36, 195, 25)
        self.last_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.last_time_label.setStyleSheet(BODY_LABEL_STYLE)
        self.last_details_label = QLabel("Завершите первый буст — данные появятся автоматически.", self.activity_panel)
        self.last_details_label.setGeometry(15, 70, 560, 22)
        self.last_details_label.setStyleSheet(BODY_LABEL_STYLE)

        self.hint_label = QLabel("Статистика хранится локально и обновляется после каждого сеанса.", self)
        self.hint_label.setGeometry(0, 390, 590, 22)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setStyleSheet(SMALL_LABEL_STYLE)

    def set_data(self, games, statistics):
        games = games if isinstance(games, (list, tuple)) else []
        statistics = statistics if isinstance(statistics, dict) else {}
        current = classify_game_statuses(games)
        library_total = len(games)
        sessions = max(0, int(statistics.get("total_sessions", 0) or 0))
        successful = max(0, int(statistics.get("successful_games", 0) or 0))
        failed = max(0, int(statistics.get("failed_games", 0) or 0))
        measured = successful + failed
        reliability = round(100 * successful / measured) if measured else 0
        self.snapshot = {
            "library_total": library_total,
            "total_sessions": sessions,
            "successful_games": successful,
            "failed_games": failed,
            "reliability": reliability,
            **current,
        }

        terminal = current["successful"] + current["failed"] + current["skipped"]
        self.library_card.set_value(_number(library_total), "текущая таблица")
        self.sessions_card.set_value(_number(sessions), f"завершено {statistics.get('completed_sessions', 0)}")
        self.success_card.set_value(_number(successful), f"ошибок {failed}")
        self.reliability_card.set_value(f"{reliability}%", "успешно / ошибки")
        self.library_summary_label.setText(f"Обработано {terminal} из {library_total}")
        self.distribution_bar.set_counts(
            current["successful"], current["failed"], current["skipped"], current["other"]
        )
        self.legend_label.setText(
            f"<span style='color:{SUCCESS_COLOR}'>●</span> Готово {current['successful']}&nbsp;&nbsp; "
            f"<span style='color:{ERROR_COLOR}'>●</span> Ошибки {current['failed']}&nbsp;&nbsp; "
            f"<span style='color:{SKIPPED_COLOR}'>●</span> Пропущено {current['skipped']}&nbsp;&nbsp; "
            f"<span style='color:{IDLE_COLOR}'>●</span> Остальные {current['other']}"
        )
        self.total_time_label.setText(
            f"Общее время: {_duration(statistics.get('total_runtime_seconds', 0))}"
        )

        last = statistics.get("last_session")
        if not isinstance(last, dict):
            self.last_summary_label.setText("Сеансов пока не было")
            self.last_time_label.clear()
            self.last_details_label.setText("Завершите первый буст — данные появятся автоматически.")
        else:
            if last.get("interrupted"):
                state = "Прерван аварийно"
            elif last.get("stopped"):
                state = "Остановлен"
            else:
                state = "Завершён"
            games_total = max(0, int(last.get("games_total", 0) or 0))
            last_success = max(0, int(last.get("successful_games", 0) or 0))
            self.last_summary_label.setText(f"{state} · {games_total} игр · готово {last_success}")
            try:
                timestamp = datetime.fromtimestamp(float(last.get("finished_at", 0)))
                self.last_time_label.setText(timestamp.strftime("%d.%m.%Y · %H:%M"))
            except (OSError, OverflowError, TypeError, ValueError):
                self.last_time_label.clear()
            self.last_details_label.setText(
                f"Длительность {_duration(last.get('duration_seconds', 0))}  ·  "
                f"Ошибки {max(0, int(last.get('failed_games', 0) or 0))}  ·  "
                f"Пропущено {max(0, int(last.get('skipped_games', 0) or 0))}"
            )

        if statistics.get("active_session"):
            self.hint_label.setText("Идёт активный сеанс — итог будет записан после его завершения.")
        else:
            self.hint_label.setText("Статистика хранится локально и обновляется после каждого сеанса.")
