from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

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
            elif col == 1:
                return str(game.get('appid', ''))
            elif col == 2:
                return str(game.get('name', ''))
            elif col == 3:
                return str(game.get('status', ''))
        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col == 0 or col == 1 or col == 3:
                return Qt.AlignmentFlag.AlignCenter
            elif col == 2:
                return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        if role == Qt.ItemDataRole.ToolTipRole and col == 2:
            return str(game.get('name', ''))
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
