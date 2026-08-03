# toast.py — виджеты для диалоговых окон

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QDialog, QLabel, QPushButton

from BoostiFy.GUI.utils.styles import (
    BG_COLOR,
    BORDER_RADIUS,
    BUTTON_STYLE,
    FONT_FAMILY,
    FONT_SIZE,
)

# Размер текста сообщений. Шрифт задаётся виджету явно, а не только через таблицу
# стилей: label.fontMetrics() возвращает метрики ШРИФТА ВИДЖЕТА, и правило
# `font-size` из stylesheet в них не попадает. Из-за этого высота строки считалась
# как 16px вместо 24px — в полтора раза меньше реальной, — и многострочные
# сообщения не помещались в отведённое место.
MESSAGE_FONT_SIZE = 18
# До какой ширины окно растягивается под текст. Дальше сообщение переносится по
# словам, а окно растёт в высоту: без предела длинная фраза расползалась в одну
# строку почти на весь экран вместо компактного окна в три строки.
MAX_TEXT_DRIVEN_WIDTH = 560


def _message_font() -> QFont:
    font = QFont(FONT_FAMILY)
    font.setPixelSize(MESSAGE_FONT_SIZE)
    return font


class _BaseDraggableDialog(QDialog):
    """
    Базовый класс для всех наших кастомных диалогов, добавляющий возможность перетаскивания.
    """
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(True)
        self.setStyleSheet(f"background-color: {BG_COLOR}; border-radius: {BORDER_RADIUS}px; padding: 4px;")
        
        self._drag_active = False
        self._drag_position = None

    def paintEvent(self, event):
        """Отрисовывает кастомную рамку и фон со скругленными углами."""
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Сначала фон
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(BG_COLOR))
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, BORDER_RADIUS, BORDER_RADIUS)
        
        # Затем рамка
        pen = QPen(QColor("#1A9AF3"), 1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect, BORDER_RADIUS-1, BORDER_RADIUS-1)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = True
            # Запоминаем смещение курсора относительно левого верхнего угла окна
            self._drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_active and event.buttons() & Qt.MouseButton.LeftButton:
            # Перемещаем окно вслед за курсором
            self.move(event.globalPosition().toPoint() - self._drag_position)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_active = False
        super().mouseReleaseEvent(event)

    def _label_padding_loss(self) -> int:
        """Сколько пикселей ширины подписи съедают её собственные поля.

        Таблица стилей диалога задаёт `padding`, и Qt применяет её ко всему поддереву,
        поэтому под текст остаётся меньше, чем сама ширина виджета. Замеряем разницу
        у живого виджета, а не берём число из стилей: так поправка останется верной,
        если оформление когда-нибудь изменится."""
        self.label.ensurePolished()
        probe_width = 200
        self.label.resize(probe_width, self.label.height() or 10)
        return max(0, probe_width - self.label.contentsRect().width())


class CustomConfirmDialog(_BaseDraggableDialog):
    """Диалог с двумя кнопками (Да/Нет)."""
    def __init__(self, parent, message, yes_text="Да", no_text="Нет"):
        super().__init__(parent)

        self.label = QLabel(message, self)
        self.label.setWordWrap(True)
        self.label.setFont(_message_font())
        self.label.setStyleSheet("color: #dcdedf; background: transparent; border: none;")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.btn_yes = QPushButton(yes_text, self)
        self.btn_yes.setStyleSheet(BUTTON_STYLE)

        self.btn_no = QPushButton(no_text, self)
        self.btn_no.setStyleSheet(BUTTON_STYLE)

        # Ширину кнопок и окна считаем по тексту, а не фиксируем: «Продолжить» в 20px
        # (размер из BUTTON_STYLE) не влезало в жёсткие 100px и обрезалось по центру до
        # «родолжит», а после расширения кнопок пара переставала помещаться в 400px окна.
        # QFontMetrics строим на пиксельном размере — как в таблице стилей, иначе замер
        # уходит в point-size и не сходится с рендером.
        self._layout(message, yes_text, no_text)

        self.btn_yes.clicked.connect(self.accept)
        self.btn_no.clicked.connect(self.reject)

    def _layout(self, message, yes_text, no_text):
        message = str(message or "")
        # Меряем только после полировки стилей: `padding` из таблицы стилей диалога
        # каскадом сужает и дочернюю подпись, а до полировки виджет об этом не знает
        # и обещает вдвое меньшую высоту, чем займёт при отрисовке.
        self.ensurePolished()
        self.label.ensurePolished()
        margin, button_gap, button_padding = 15, 30, 40
        top_margin, text_button_gap = 15, 10
        button_height, bottom_margin = 35, 15
        min_w, min_h = 400, 160
        max_w, max_h = 800, 600

        button_font = QFont(FONT_FAMILY)
        button_font.setPixelSize(FONT_SIZE)
        button_metrics = QFontMetrics(button_font)
        width_yes = max(100, button_metrics.horizontalAdvance(yes_text) + button_padding)
        width_no = max(100, button_metrics.horizontalAdvance(no_text) + button_padding)
        buttons_total = width_yes + button_gap + width_no

        # Расширяем окно по самой длинной явной строке, но оставляем верхнюю границу:
        # слишком длинный текст будет аккуратно перенесён внутри окна.
        text_metrics = self.label.fontMetrics()
        longest_line = max(
            (text_metrics.horizontalAdvance(line) for line in message.split('\n')),
            default=0,
        )
        # Прибавляем то, что подпись теряет на собственных полях: `padding` из таблицы
        # стилей диалога достаётся ей каскадом. Без этой поправки строка, под которую
        # окно и рассчитано, не влезала буквально на несколько пикселей — и последнее
        # слово уезжало на отдельную строку, оставляя некрасивую «сироту».
        padding_loss = self._label_padding_loss()
        dialog_width = min(
            max(
                min_w,
                min(longest_line + padding_loss + 2 * margin, MAX_TEXT_DRIVEN_WIDTH),
                buttons_total + 2 * margin,
            ),
            max_w,
        )
        label_width = int(dialog_width) - 2 * margin

        # Высоту спрашиваем у самого QLabel: QFontMetrics.boundingRect переносит текст
        # не так, как виджет (для этого сообщения — 48px против реальных 104px), поэтому
        # окно выходило втрое ниже нужного и текст вылезал за края.
        label_height = max(text_metrics.height(), self.label.heightForWidth(label_width))
        required_height = (
            top_margin
            + label_height
            + text_button_gap
            + button_height
            + bottom_margin
        )
        dialog_height = min(max(min_h, required_height), max_h)
        self.setFixedSize(int(dialog_width), int(dialog_height))

        button_y = int(dialog_height) - bottom_margin - button_height
        available_label_height = max(
            text_metrics.height(),
            button_y - top_margin - text_button_gap,
        )
        self.label.setGeometry(margin, top_margin, label_width, available_label_height)

        start_x = (int(dialog_width) - buttons_total) // 2
        self.btn_yes.setGeometry(start_x, button_y, width_yes, button_height)
        self.btn_no.setGeometry(
            start_x + width_yes + button_gap,
            button_y,
            width_no,
            button_height,
        )

class InfoDialog(_BaseDraggableDialog):
    """Диалог с одной кнопкой (OK) и динамическим размером."""
    def __init__(self, parent, message, ok_text="ОК"):
        super().__init__(parent)
        
        self.label = QLabel(message, self)
        self.label.setWordWrap(True)
        self.label.setFont(_message_font())
        self.label.setStyleSheet("color: #dcdedf; background: transparent; border: none;")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.btn_ok = QPushButton(ok_text, self)
        self.btn_ok.setStyleSheet(BUTTON_STYLE)
        self.btn_ok.clicked.connect(self._on_ok)
        
        # Автоматически определяем и устанавливаем размер окна
        self._set_dynamic_size(message)

    def _on_ok(self):
        self.accept()
        self.close()

    def _set_dynamic_size(self, message):
        """Вычисляет оптимальный размер окна на основе длины текста."""
        message = str(message or "")
        # См. CustomConfirmDialog._layout: без полировки замер не учитывает padding,
        # который каскадом достаётся подписи от таблицы стилей диалога.
        self.ensurePolished()
        self.label.ensurePolished()
        min_w, min_h = 400, 160
        max_w, max_h = 800, 600 # Ограничим максимальный размер

        # Получаем метрики шрифта для точных расчетов
        fm = self.label.fontMetrics()

        # Оцениваем ширину по самой длинной строке
        lines = message.split('\n')
        text_width = min(
            # +поля подписи, иначе строка, под которую подобрана ширина, не влезает
            # на несколько пикселей и последнее слово уезжает на отдельную строку.
            max(fm.horizontalAdvance(line) for line in lines) + 40 + self._label_padding_loss(),
            MAX_TEXT_DRIVEN_WIDTH,
        )
        w = min(max(text_width, min_w), max_w)

        # Высота — по фактическому переносу по словам на итоговой ширине (а не по числу '\n'),
        # иначе длинные сообщения без \n обрезаются.
        # Высоту берём у виджета, а не у QFontMetrics: их перенос по словам расходится.
        text_height = self.label.heightForWidth(int(w) - 30) + 80  # + место для кнопки и отступы
        h = min(max(text_height, min_h), max_h)
        
        self.setFixedSize(int(w), int(h))
        self.label.setGeometry(15, 15, int(w) - 30, int(h) - 70)
        self.btn_ok.setGeometry((int(w) - 100) // 2, int(h) - 50, 100, 35)
        
    # --- "Пустые" методы, которые были в конце, удалены, так как они не использовались. ---