# toast.py — виджеты для диалоговых окон

from PyQt6.QtWidgets import QDialog, QLabel, QPushButton
from PyQt6.QtCore import Qt, QRect
from PyQt6.QtGui import QPainter, QColor, QPen
from BoostiFy.GUI.utils.styles import BG_COLOR, BUTTON_STYLE, BORDER_RADIUS

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


class CustomConfirmDialog(_BaseDraggableDialog):
    """Диалог с двумя кнопками (Да/Нет)."""
    def __init__(self, parent, message, yes_text="Да", no_text="Нет"):
        super().__init__(parent)
        self.setFixedSize(400, 160)
        
        self.label = QLabel(message, self)
        self.label.setWordWrap(True)
        self.label.setGeometry(15, 15, 370, 90)
        self.label.setStyleSheet("color: #dcdedf; font-size: 18px; background: transparent; border: none;")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.btn_yes = QPushButton(yes_text, self)
        self.btn_yes.setGeometry(70, 110, 100, 35)
        self.btn_yes.setStyleSheet(BUTTON_STYLE)
        
        self.btn_no = QPushButton(no_text, self)
        self.btn_no.setGeometry(230, 110, 100, 35)
        self.btn_no.setStyleSheet(BUTTON_STYLE)
        
        self.btn_yes.clicked.connect(self.accept)
        self.btn_no.clicked.connect(self.reject)


class InfoDialog(_BaseDraggableDialog):
    """Диалог с одной кнопкой (OK) и динамическим размером."""
    def __init__(self, parent, message, ok_text="ОК"):
        super().__init__(parent)
        
        self.label = QLabel(message, self)
        self.label.setWordWrap(True)
        self.label.setStyleSheet("color: #dcdedf; font-size: 18px; background: transparent; border: none;")
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
        min_w, min_h = 400, 160
        max_w, max_h = 800, 600 # Ограничим максимальный размер

        # Получаем метрики шрифта для точных расчетов
        fm = self.label.fontMetrics()

        # Оцениваем ширину по самой длинной строке
        lines = message.split('\n')
        text_width = max(fm.horizontalAdvance(line) for line in lines) + 40 # + отступы
        w = min(max(text_width, min_w), max_w)

        # Высота — по фактическому переносу по словам на итоговой ширине (а не по числу '\n'),
        # иначе длинные сообщения без \n обрезаются.
        wrapped = fm.boundingRect(QRect(0, 0, int(w) - 30, 0), Qt.TextFlag.TextWordWrap, message)
        text_height = wrapped.height() + 80  # + место для кнопки и отступы
        h = min(max(text_height, min_h), max_h)
        
        self.setFixedSize(int(w), int(h))
        self.label.setGeometry(15, 15, int(w) - 30, int(h) - 70)
        self.btn_ok.setGeometry((int(w) - 100) // 2, int(h) - 50, 100, 35)
        
    # --- "Пустые" методы, которые были в конце, удалены, так как они не использовались. ---