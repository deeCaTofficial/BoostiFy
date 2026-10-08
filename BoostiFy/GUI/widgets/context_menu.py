# context_menu.py — контекстное меню поля ввода в стиле приложения

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import QApplication, QMenu

from BoostiFy.GUI.utils.styles import (
    ACTIVE_COLOR,
    BORDER_RADIUS,
    ELEMENT_BG_COLOR,
    FONT_FAMILY,
    TEXT_COLOR,
)

# Меню Qt по умолчанию приносит светлую системную рамку, иконки-заготовки и
# английские подписи — на тёмной плашке это выглядит куском чужой программы.
# Собираем своё: те же цвета, скругление и шрифт, что у кнопок и панелей.
MENU_STYLE = f"""
    QMenu {{
        background-color: {ELEMENT_BG_COLOR};
        color: {TEXT_COLOR};
        border: 1px solid #3a4757;
        border-radius: {BORDER_RADIUS}px;
        padding: 6px;
        font-family: '{FONT_FAMILY}';
        font-size: 16px;
    }}
    QMenu::item {{
        background: transparent;
        /* Правое поле держит колонку с сочетанием клавиш: без запаса Qt прижимает
           её вплотную к подписи, и получается «Выделить всёCtrl+A». */
        padding: 8px 16px 8px 14px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{
        background-color: {ACTIVE_COLOR};
        color: #ffffff;
    }}
    QMenu::item:disabled {{
        color: #5d6b7c;
    }}
    QMenu::separator {{
        height: 1px;
        background: #3a4757;
        margin: 5px 10px;
    }}
"""


def _add(menu, title, shortcut, enabled, handler):
    action = QAction(title, menu)
    if shortcut is not None:
        action.setShortcut(shortcut)
    action.setEnabled(bool(enabled))
    action.triggered.connect(handler)
    menu.addAction(action)
    return action


def build_text_context_menu(line_edit) -> QMenu:
    """Меню для QLineEdit: копировать, вставить, удалить.

    Отмены, повтора, «выделить всё» и «вырезать» здесь намеренно нет. Поле
    рассчитано на одну короткую строку — AppID или название игры: история правок в
    нём никому не нужна, выделить строку целиком проще тройным щелчком или Ctrl+A,
    а вырезать — это то же удаление, только с попутной записью в буфер. Пункты
    занимали половину меню и ничего не давали.
    """
    # Родитель — окно, а не само поле ввода. Таблица стилей Qt каскадом достаётся
    # всему поддереву, а у поля в стиле есть qproperty-alignment: у QMenu такого
    # свойства нет, и Qt на каждый вызов писал в консоль «does not have a property
    # named "alignment"». Заодно меню перестаёт наследовать заливку, поля и
    # скругление поля ввода. Совсем без родителя тоже нельзя: меню тут же собирал
    # сборщик мусора вместе с пунктами.
    menu = QMenu(line_edit.window())
    menu.setStyleSheet(MENU_STYLE)
    # Скругление рисуется только поверх прозрачного фона: иначе за скруглённой
    # плашкой остаются непрозрачные прямые углы самого окна меню.
    menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint)
    menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    has_selection = line_edit.hasSelectedText()
    editable = not line_edit.isReadOnly()
    clipboard = QApplication.clipboard()
    can_paste = editable and bool(clipboard is not None and clipboard.text())

    _add(menu, "Копировать", QKeySequence.StandardKey.Copy,
         has_selection, line_edit.copy)
    _add(menu, "Вставить", QKeySequence.StandardKey.Paste,
         can_paste, line_edit.paste)
    menu.addSeparator()
    _add(menu, "Удалить", QKeySequence.StandardKey.Delete,
         has_selection and editable, lambda: line_edit.del_())
    return menu


def show_text_context_menu(line_edit, position):
    """Показывает меню в точке щелчка. Возвращает выбранное действие или None."""
    menu = build_text_context_menu(line_edit)
    try:
        return menu.exec(line_edit.mapToGlobal(position))
    finally:
        # Владелец — окно, поэтому само оно меню не освободит: без этого каждый
        # щелчок правой кнопкой оставлял бы висеть ещё одно меню до закрытия окна.
        menu.deleteLater()
