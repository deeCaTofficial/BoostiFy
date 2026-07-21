import threading
import traceback

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

    @pyqtSlot()
    def run(self):
        try:
            result = self.function(self.cancel_event, self.signals.progress.emit)
        except Exception as error:
            if not isinstance(error, (ValueError, RuntimeError, FileNotFoundError)):
                traceback.print_exc()
            self.signals.error.emit(str(error) or error.__class__.__name__)
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()
