from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import QFrame, QLabel, QPushButton, QWidget

from BoostiFy.GUI.core.statistics_storage import classify_game_statuses
from BoostiFy.GUI.utils.styles import (
    ACTIVE_COLOR,
    BUTTON_STYLE,
    ELEMENT_BG_COLOR,
    FONT_FAMILY,
    TEXT_COLOR,
)

SUCCESS_COLOR = "#41c98d"
ERROR_COLOR = "#ff6b6b"
SKIPPED_COLOR = "#f5b84b"
IDLE_COLOR = "#465362"
MUTED_COLOR = "#8b98a5"
TRACK_COLOR = "#202832"

# Тот же визуальный язык, что и у остальных вкладок: плашка ELEMENT_BG_COLOR,
# скругление 10px, Segoe UI. Держим мало типоразмеров шрифта — так экран перестаёт
# «частить» на фоне спокойных вкладок с крупными кнопками.
CARD_STYLE = f"""
    QFrame#statisticsCard, QFrame#statisticsPanel {{
        background-color: {ELEMENT_BG_COLOR};
        border: none;
        border-radius: 10px;
    }}
"""
CAPTION_STYLE = (
    f"color: {MUTED_COLOR}; background: transparent; "
    f"font-family: '{FONT_FAMILY}'; font-size: 14px; font-weight: 600;"
)
BODY_STYLE = (
    f"color: {TEXT_COLOR}; background: transparent; "
    f"font-family: '{FONT_FAMILY}'; font-size: 15px;"
)


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
        painter.fillPath(path, QColor(TRACK_COLOR))
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
    """Плитка-показатель: подпись сверху, крупное число снизу. Без мелкой третьей
    строки — она добавляла шума, а суть метрики уже в подписи."""

    def __init__(self, caption, accent=ACTIVE_COLOR, parent=None):
        super().__init__(parent)
        self.setObjectName("statisticsCard")
        self.setStyleSheet(CARD_STYLE)
        self.caption_label = QLabel(caption, self)
        self.caption_label.setGeometry(16, 16, 108, 18)
        self.caption_label.setStyleSheet(CAPTION_STYLE)
        self.value_label = QLabel("0", self)
        self.value_label.setGeometry(16, 40, 108, 40)
        self.value_label.setStyleSheet(
            f"color: {accent}; background: transparent; font-family: '{FONT_FAMILY}'; "
            "font-size: 30px; font-weight: 700;"
        )

    def set_value(self, value):
        self.value_label.setText(str(value))


class StatisticsPanel(QWidget):
    refresh_requested = pyqtSignal()
    reset_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.snapshot = {}

        # Заголовок «Обзор активности» убран намеренно: раздел уже подписан в левой
        # навигации («Статистика»), а внутренний дубль-заголовок ломал ритм вкладок.
        # Верхний ряд отдан под действия — как ряд кнопок на других страницах.
        self.refresh_button = QPushButton("Обновить", self)
        self.refresh_button.setGeometry(0, 0, 287, 45)
        self.refresh_button.setStyleSheet(BUTTON_STYLE)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)

        self.reset_button = QPushButton("Сбросить", self)
        self.reset_button.setGeometry(303, 0, 287, 45)
        self.reset_button.setStyleSheet(BUTTON_STYLE)
        self.reset_button.clicked.connect(self.reset_requested.emit)

        # Ряд показателей: четыре плитки одной высоты, как крупные плашки вкладок.
        self.library_card = StatisticsCard("Игр в списке", MUTED_COLOR, self)
        self.sessions_card = StatisticsCard("Сеансов", TEXT_COLOR, self)
        self.success_card = StatisticsCard("Успешно", SUCCESS_COLOR, self)
        self.reliability_card = StatisticsCard("Надёжность", ACTIVE_COLOR, self)
        for index, card in enumerate(
            (self.library_card, self.sessions_card, self.success_card, self.reliability_card)
        ):
            card.setGeometry(index * 150, 63, 140, 96)

        # Панель «Текущая таблица»: подпись + сводка, полоса распределения, легенда.
        self.library_panel = QFrame(self)
        self.library_panel.setObjectName("statisticsPanel")
        self.library_panel.setGeometry(0, 177, 590, 110)
        self.library_panel.setStyleSheet(CARD_STYLE)
        library_title = QLabel("Текущая таблица", self.library_panel)
        library_title.setGeometry(18, 16, 300, 20)
        library_title.setStyleSheet(CAPTION_STYLE)
        self.library_summary_label = QLabel("", self.library_panel)
        self.library_summary_label.setGeometry(272, 16, 300, 20)
        self.library_summary_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.library_summary_label.setStyleSheet(CAPTION_STYLE)
        self.distribution_bar = StatusDistributionBar(self.library_panel)
        self.distribution_bar.setGeometry(18, 48, 554, 16)
        self.legend_label = QLabel("", self.library_panel)
        self.legend_label.setGeometry(18, 76, 554, 24)
        self.legend_label.setTextFormat(Qt.TextFormat.RichText)
        self.legend_label.setStyleSheet(BODY_STYLE)

        # Панель «Последний сеанс»: итог одной строкой + время справа + детали снизу.
        self.activity_panel = QFrame(self)
        self.activity_panel.setObjectName("statisticsPanel")
        self.activity_panel.setGeometry(0, 299, 590, 106)
        self.activity_panel.setStyleSheet(CARD_STYLE)
        activity_title = QLabel("Последний сеанс", self.activity_panel)
        activity_title.setGeometry(18, 14, 260, 20)
        activity_title.setStyleSheet(CAPTION_STYLE)
        self.total_time_label = QLabel("Общее время: 0 сек.", self.activity_panel)
        self.total_time_label.setGeometry(272, 14, 300, 20)
        self.total_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.total_time_label.setStyleSheet(CAPTION_STYLE)
        self.last_summary_label = QLabel("Сеансов пока не было", self.activity_panel)
        self.last_summary_label.setGeometry(18, 40, 360, 26)
        self.last_summary_label.setStyleSheet(
            f"color: {TEXT_COLOR}; background: transparent; font-family: '{FONT_FAMILY}'; "
            "font-size: 19px; font-weight: 600;"
        )
        self.last_time_label = QLabel("", self.activity_panel)
        self.last_time_label.setGeometry(372, 40, 200, 26)
        self.last_time_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.last_time_label.setStyleSheet(BODY_STYLE)
        self.last_details_label = QLabel("Завершите первый буст — данные появятся здесь.", self.activity_panel)
        self.last_details_label.setGeometry(18, 74, 554, 22)
        self.last_details_label.setStyleSheet(
            f"color: {MUTED_COLOR}; background: transparent; "
            f"font-family: '{FONT_FAMILY}'; font-size: 14px;"
        )

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
        self.library_card.set_value(_number(library_total))
        self.sessions_card.set_value(_number(sessions))
        self.success_card.set_value(_number(successful))
        self.reliability_card.set_value(f"{reliability}%")
        self.library_summary_label.setText(f"Обработано {terminal} из {library_total}")
        self.distribution_bar.set_counts(
            current["successful"], current["failed"], current["skipped"], current["other"]
        )
        self.legend_label.setText(
            f"<span style='color:{SUCCESS_COLOR}'>●</span> Готово {current['successful']}&nbsp;&nbsp;&nbsp; "
            f"<span style='color:{ERROR_COLOR}'>●</span> Ошибки {current['failed']}&nbsp;&nbsp;&nbsp; "
            f"<span style='color:{SKIPPED_COLOR}'>●</span> Пропущено {current['skipped']}&nbsp;&nbsp;&nbsp; "
            f"<span style='color:{IDLE_COLOR}'>●</span> Остальные {current['other']}"
        )
        self.total_time_label.setText(
            f"Общее время: {_duration(statistics.get('total_runtime_seconds', 0))}"
        )

        last = statistics.get("last_session")
        if not isinstance(last, dict):
            self.last_summary_label.setText("Сеансов пока не было")
            self.last_time_label.clear()
            self.last_details_label.setText("Завершите первый буст — данные появятся здесь.")
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
