import threading
import traceback

from PyQt6 import sip
from PyQt6.QtCore import QObject, QRunnable, pyqtSignal, pyqtSlot


class TaskSignals(QObject):
    result = pyqtSignal(object)
    error = pyqtSignal(str)
    progress = pyqtSignal(object)
    finished = pyqtSignal()


class BackgroundTask(QRunnable):
    """Cancellable QThreadPool task with all callbacks delivered through Qt signals."""

    def __init__(self, function):
        super().__init__()
        self.function = function
        self.cancel_event = threading.Event()
        self.signals = TaskSignals()

    def cancel(self):
        self.cancel_event.set()

    def _emit(self, name, *args):
        """Отправляет сигнал по имени, переживая уничтожение своего QObject.

        Задача живёт в пуле потоков и завершается уже после закрытия окна: к этому
        моменту TaskSignals может быть уничтожен, и обращение к сигналу бросает
        RuntimeError прямо в рабочем потоке. Раньше это исключение всплывало из
        QRunnable.run и роняло выход («wrapped C/C++ object ... has been deleted»).
        Имя, а не сам сигнал: доступ к атрибуту уничтоженного QObject падает ещё до
        вызова, поэтому его тоже держим внутри try."""
        signals = self.signals
        try:
            if sip.isdeleted(signals):
                return
            getattr(signals, name).emit(*args)
        except RuntimeError:
            pass  # QObject уничтожен между проверкой и отправкой

    @pyqtSlot()
    def run(self):
        try:
            result = self.function(
                self.cancel_event, lambda value: self._emit("progress", value)
            )
        except Exception as error:
            if not isinstance(error, (ValueError, RuntimeError, FileNotFoundError)):
                traceback.print_exc()
            self._emit("error", str(error) or error.__class__.__name__)
        else:
            self._emit("result", result)
        finally:
            self._emit("finished")
