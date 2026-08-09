
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
    """Плитка-показатель: подпись сверху, значение снизу.

    Подписи по центру — как во всех остальных вкладках настроек, где текст набран
    стилем с qproperty-alignment: AlignCenter. Ширину подписи и значения плитка
    подгоняет сама при изменении размера, поэтому одна и та же плитка годится и для
    узкого ряда показателей, и для широких карточек последнего сеанса."""

    def __init__(self, caption, accent=ACTIVE_COLOR, parent=None, value_size=30):
        super().__init__(parent)
        self.setObjectName("statisticsCard")
        self.setStyleSheet(CARD_STYLE)
        self._value_size = value_size
        self.caption_label = QLabel(caption, self)
        self.caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.caption_label.setStyleSheet(CAPTION_STYLE)
        self.value_label = QLabel("0", self)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_accent(accent)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        inner = max(0, self.width() - 16)
        self.caption_label.setGeometry(8, 32, inner, 18)
        self.value_label.setGeometry(8, 56, inner, 42)

    def set_accent(self, color):
        self.value_label.setStyleSheet(
            f"color: {color}; background: transparent; font-family: '{FONT_FAMILY}'; "
            f"font-size: {self._value_size}px; font-weight: 700;"
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

        # Вся правая часть выровнена по сетке левого меню: его кнопки заканчиваются
        # на 45, 120, 195, 270, 345 и 420 (в координатах этой области), поэтому и блоки
        # обрываются ровно на этих же линиях. Раньше они стояли на своих 63/177/299 —
        # отсюда и ощущение перекоса.
        self.library_card = StatisticsCard("Игр в списке", MUTED_COLOR, self)
        self.sessions_card = StatisticsCard("Сеансов", TEXT_COLOR, self)
        self.success_card = StatisticsCard("Успешно", SUCCESS_COLOR, self)
        self.reliability_card = StatisticsCard("Надёжность", ACTIVE_COLOR, self)
        # Плитки делим на две половины ровно по кнопкам сверху: правый край второй
        # плитки совпадает с правым краем «Обновить» (287), а третья начинается там же,
        # где «Сбросить» (303). Раньше шаг был свой (150 через 10), и средний разрыв
        # не совпадал с разрывом между кнопками — колонка выглядела сдвинутой.
        for card, x in zip(
            (self.library_card, self.sessions_card, self.success_card, self.reliability_card),
            (0, 149, 303, 452),
            strict=True,
        ):
            card.setGeometry(x, 75, 138, 120)

        # Состояние таблицы: полоса и подписи к ней. Заголовок и «Обработано N из M»
        # убраны — полоса с легендой говорят ровно то же самое, только без слов.
        self.library_panel = QFrame(self)
        self.library_panel.setObjectName("statisticsPanel")
        self.library_panel.setGeometry(0, 225, 590, 45)
        self.library_panel.setStyleSheet(CARD_STYLE)
        self.distribution_bar = StatusDistributionBar(self.library_panel)
        self.distribution_bar.setGeometry(18, 11, 554, 6)
        self.legend_label = QLabel("", self.library_panel)
        self.legend_label.setGeometry(18, 21, 554, 20)
        self.legend_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.legend_label.setTextFormat(Qt.TextFormat.RichText)
        self.legend_label.setStyleSheet(BODY_STYLE)

        # Последний сеанс — три отдельные карточки, а не колонки внутри одной плашки:
        # нижний ряд подхватывает ритм верхнего, и оба читаются как один список
        # показателей. Отдельной подписи над ними нет — ряд говорит сам за себя.
        self.outcome_card = StatisticsCard("Итог", MUTED_COLOR, self, value_size=19)
        self.games_card = StatisticsCard("Готово", TEXT_COLOR, self, value_size=19)
        self.duration_card = StatisticsCard("Время", TEXT_COLOR, self, value_size=19)
        # Три карточки по 186 с зазором 16 — средняя встаёт ровно по центральной оси
        # (295), той же, что разделяет кнопки и половины ряда плиток.
        for card, x in zip(
            (self.outcome_card, self.games_card, self.duration_card),
            (0, 202, 404),
            strict=True,
        ):
            card.setGeometry(x, 300, 186, 120)

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

        self.library_card.set_value(_number(library_total))
        self.sessions_card.set_value(_number(sessions))
        self.success_card.set_value(_number(successful))
        self.reliability_card.set_value(f"{reliability}%")
        self.distribution_bar.set_counts(
            current["successful"], current["failed"], current["skipped"], current["other"]
        )
        # Только цветная точка и число: слова «Готово/Ошибки/Пропущено» дублировали
        # цвета полосы над легендой и занимали строку целиком.
        self.legend_label.setText(
            f"<span style='color:{SUCCESS_COLOR}'>●</span> Готово {_number(current['successful'])}"
            f"&nbsp;&nbsp;&nbsp;&nbsp;<span style='color:{ERROR_COLOR}'>●</span> Ошибки {_number(current['failed'])}"
            f"&nbsp;&nbsp;&nbsp;&nbsp;<span style='color:{SKIPPED_COLOR}'>●</span> Пропущено {_number(current['skipped'])}"
            f"&nbsp;&nbsp;&nbsp;&nbsp;<span style='color:{IDLE_COLOR}'>●</span> В очереди {_number(current['other'])}"
        )

        last = statistics.get("last_session")
        if not isinstance(last, dict):
            self.outcome_card.set_value("—")
            self.outcome_card.set_accent(MUTED_COLOR)
            self.games_card.set_value("—")
            self.duration_card.set_value("—")
            return

        if last.get("interrupted"):
            state, accent = "Прерван", ERROR_COLOR
        elif last.get("stopped"):
            state, accent = "Остановлен", SKIPPED_COLOR
        else:
            state, accent = "Завершён", SUCCESS_COLOR
        # Итог подкрашиваем по исходу: цвет считывается быстрее слова.
        self.outcome_card.set_value(state)
        self.outcome_card.set_accent(accent)

        games_total = max(0, int(last.get("games_total", 0) or 0))
        last_success = max(0, int(last.get("successful_games", 0) or 0))
        self.games_card.set_value(f"{_number(last_success)} из {_number(games_total)}")
        self.duration_card.set_value(_duration(last.get("duration_seconds", 0)))
