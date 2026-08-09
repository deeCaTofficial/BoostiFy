# custom_title_bar.py — виджет CustomTitleBar

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QAbstractButton, QWidget


class TitleBarButton(QAbstractButton):
    """Кнопка заголовка окна с векторным значком.

    Значки были текстом — «—» и «✕» шрифтом 16px. Глиф целиком зависит от
    начертания: тире вставало выше оптического центра, а крестик выходил заметно
    крупнее и жирнее него, и пара смотрелась разнокалиберной. Рисуем сами: одна
    толщина линии на оба значка, общий центр и одинаковый размер.
    """

    ICON_COLOR = QColor("#b7c0cb")
    ICON_ACTIVE_COLOR = QColor("#ffffff")
    # Подложка при наведении: у «свернуть» — едва заметная светлая, у «закрыть»
    # красная. Красный на закрытии — привычка из любого окна Windows, читается
    # быстрее любой подписи и страхует от промаха по соседней кнопке.
    HOVER_BG = QColor(255, 255, 255, 24)
    CLOSE_HOVER_BG = QColor("#e05561")
    RADIUS = 6
    STROKE = 1.5
    ICON_HALF = 4.5

    def __init__(self, kind, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._hovered = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def _background(self):
        if not (self._hovered or self.isDown()):
            return None
        color = self.CLOSE_HOVER_BG if self._kind == "close" else self.HOVER_BG
        return color.darker(125) if self.isDown() else color

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = self._background()
        if background is not None:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(background)
            painter.drawRoundedRect(QRectF(self.rect()), self.RADIUS, self.RADIUS)

        highlighted = self._kind == "close" and background is not None
        pen = QPen(self.ICON_ACTIVE_COLOR if highlighted else self.ICON_COLOR, self.STROKE)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        center = QRectF(self.rect()).center()
        # Половина пикселя: линия толщиной STROKE, положенная на целую координату,
        # растекается на два ряда пикселей и выглядит размытой.
        cx = round(center.x()) + 0.5
        cy = round(center.y()) + 0.5
        half = self.ICON_HALF
        if self._kind == "close":
            painter.drawLine(QPointF(cx - half, cy - half), QPointF(cx + half, cy + half))
            painter.drawLine(QPointF(cx + half, cy - half), QPointF(cx - half, cy + half))
        else:
            # Тире чуть шире половины крестика: у одиночной линии нет второй
            # диагонали, и при равной длине она смотрится короче.
            painter.drawLine(QPointF(cx - half - 1, cy), QPointF(cx + half + 1, cy))


class CustomTitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setFixedHeight(30)
        # Кнопки квадратные: подложка при наведении у прежних 30x20 вытягивалась
        # в лежачий прямоугольник вокруг маленького значка. Центры значков оставляем
        # на прежних 885 и 925, чтобы шапка не сдвинулась относительно логотипа.
        self.minimize_button = TitleBarButton("minimize", self)
        self.minimize_button.setGeometry(873, 3, 24, 24)
        self.minimize_button.clicked.connect(self.parent_window.showMinimized)
        self.close_button = TitleBarButton("close", self)
        self.close_button.setGeometry(913, 3, 24, 24)
        self.close_button.clicked.connect(self.parent_window.close)
        self._drag_pos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.parent_window.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.parent_window.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()
