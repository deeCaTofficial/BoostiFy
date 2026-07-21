# custom_title_bar.py — виджет CustomTitleBar

from PyQt6.QtWidgets import QWidget, QPushButton
from PyQt6.QtCore import Qt

class CustomTitleBar(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setFixedHeight(30)
        self.minimize_button = QPushButton("—", self)
        self.minimize_button.setGeometry(960 - 90, 5, 30, 20)
        self.minimize_button.clicked.connect(self.parent_window.showMinimized)
        self.close_button = QPushButton("✕", self)
        self.close_button.setGeometry(960 - 50, 5, 30, 20)
        self.close_button.clicked.connect(self.parent_window.close)
        style = "QPushButton { background-color: transparent; border: none; color: #dcdedf; font-size: 16px; font-weight: bold; } QPushButton:hover { color: #1A9AF3; }"
        self.minimize_button.setStyleSheet(style)
        self.close_button.setStyleSheet(style)
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
