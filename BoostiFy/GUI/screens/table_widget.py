from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt


def _short_status(status) -> str:
    """Короткий статус для таблицы: только слово до двоеточия.

    Причина сбоя в столбец не помещается и обрезается многоточием, поэтому в
    таблице остаётся «Ошибка», а разбор уходит в журнал. Сокращаем при отрисовке,
    а не при записи: в user_games.json лежат статусы, сохранённые прошлыми
    запусками, и они точно так же должны показываться коротко."""
    text = str(status or '').strip()
    return text.split(':', 1)[0].strip() if ':' in text else text


class GameTableModel(QAbstractTableModel):
    def __init__(self, games=None):
        super().__init__()
        self._games = games or []
        self._headers = ["№", "AppID", "Название", "Статус"]

    def rowCount(self, parent=QModelIndex()):
        return len(self._games)

    def columnCount(self, parent=QModelIndex()):
        return 4

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if row < 0 or row >= len(self._games):
            return None
        game = self._games[row]
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return str(row + 1)
            if col == 1:
                return str(game.get('appid', ''))
            if col == 2:
                return str(game.get('name', ''))
            if col == 3:
                return _short_status(game.get('status', ''))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col == 0 or col == 1 or col == 3:
                return Qt.AlignmentFlag.AlignCenter
            if col == 2:
                return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        if role == Qt.ItemDataRole.ToolTipRole:
            # Длинное название в столбец не помещается — показываем целиком.
            if col == 2:
                return str(game.get('name', ''))
            if col == 3:
                status = str(game.get('status', '')).strip()
                if not status.startswith('Ошибка'):
                    return status
                # Подробности сбоя живут в журнале. У записей, сохранённых прежними
                # версиями, причина осталась в самом статусе — показываем и её.
                hint = 'Подробности — в журнале сбоев:\n%LOCALAPPDATA%\\BoostiFy\\logs\\boost_errors.log'
                return f'{status}\n\n{hint}' if ':' in status else hint
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._headers[section]
        return None

    def set_games(self, games):
        self.beginResetModel()
        self._games = games
        self.endResetModel()

    def get_game(self, row):
        if 0 <= row < len(self._games):
            return self._games[row]
        return None
