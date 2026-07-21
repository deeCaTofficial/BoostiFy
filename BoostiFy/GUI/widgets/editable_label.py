# editable_label.py — виджет EditableLabel

from PyQt6.QtWidgets import QWidget, QLabel, QLineEdit
from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal
from BoostiFy.GUI.utils.styles import LABEL_AS_BUTTON_STYLE

class EditableLabel(QWidget):
    # Сигнал для добавления игры по Enter
    enter_pressed = pyqtSignal(str)
    text_changed = pyqtSignal(str)
    
    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.placeholder = text
        self.label = QLabel(text, self)
        self.label.setStyleSheet(LABEL_AS_BUTTON_STYLE)
        self.label.setGeometry(0, 0, 280, 45)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.mousePressEvent = self._on_label_click
        
        self.edit = QLineEdit('', self)
        self.edit.setStyleSheet(LABEL_AS_BUTTON_STYLE)
        self.edit.setGeometry(0, 0, 280, 45)
        self.edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit.setPlaceholderText(self.placeholder)
        self.edit.hide()
        
        # Таймер для авто-снятия фокуса
        self.blur_timer = QTimer(self)
        self.blur_timer.setInterval(3000)
        self.blur_timer.setSingleShot(True)
        self.blur_timer.timeout.connect(self._auto_clear_focus)
        
        # Подключаем сигналы
        self.edit.returnPressed.connect(self.on_enter_pressed)
        self.edit.editingFinished.connect(self.finish_edit)
        self.installEventFilter(self)
        self.edit.installEventFilter(self)  # чтобы Esc в поле ввода реально ловился (obj == self.edit)
        self.edit.textEdited.connect(self._reset_blur_timer)
        self.edit.textEdited.connect(self._emit_text_changed)
    
    def _reset_blur_timer(self):
        self.blur_timer.start()
    
    def _auto_clear_focus(self):
        if self.edit.hasFocus():
            self.edit.clearFocus()
    
    def mousePressEvent(self, event):
        self.start_edit()
    
    def start_edit(self):
        self.label.hide()
        self.edit.setText(self.label.text() if self.label.text() != self.placeholder else '')
        self.edit.show()
        self.edit.setFocus()
        self.edit.selectAll()
        self.blur_timer.start()
    
    def finish_edit(self):
        text = self.edit.text().strip()
        self.label.setText(text if text else self.placeholder)
        self.edit.hide()
        self.label.show()
        self.blur_timer.stop()
    
    def on_enter_pressed(self):
        """Обработчик нажатия Enter - эмитим сигнал с текстом"""
        text = self.edit.text().strip()
        if text:  # Эмитим сигнал только если есть текст
            self.enter_pressed.emit(text)
        # Всегда очищаем поле и устанавливаем плейсхолдер
        self.edit.clear()
        self.label.setText(self.placeholder)
        self.edit.hide()
        self.label.show()
        self.blur_timer.stop()
    
    def _emit_text_changed(self):
        self.text_changed.emit(self.edit.text())
    
    def eventFilter(self, obj, event):
        if event.type() == event.Type.FocusOut and obj is self and self.edit.isVisible():
            self.finish_edit()
        # Сброс фильтра по Esc
        if obj == self.edit and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            self.edit.clear()
            self.text_changed.emit("")
            return True
        return super().eventFilter(obj, event)

    def _on_label_click(self, ev):
        self.start_edit()
 