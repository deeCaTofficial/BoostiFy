import atexit
import ctypes
import os
import sys
import threading

from BoostiFy.core.app_paths import LOG_DIR, ensure_app_directories
from BoostiFy.GUI.core.game_storage import ensure_storage_ready


class RotatingLogSink:
    def __init__(self, path, max_bytes=5 * 1024 * 1024, backups=3):
        self.path = path
        self.max_bytes = max_bytes
        self.backups = backups
        self._lock = threading.RLock()
        self._stream = self.path.open("a", encoding="utf-8")

    def _rotate_if_needed(self, text):
        try:
            current_size = self.path.stat().st_size
        except OSError:
            current_size = 0
        if current_size + len(text.encode("utf-8", errors="replace")) <= self.max_bytes:
            return
        self._stream.close()
        for index in range(self.backups, 0, -1):
            source = self.path.with_name(self.path.name if index == 1 else f"{self.path.name}.{index - 1}")
            target = self.path.with_name(f"{self.path.name}.{index}")
            if source.exists():
                try:
                    os.replace(source, target)
                except OSError:
                    pass
        self._stream = self.path.open("a", encoding="utf-8")

    def write(self, text):
        if not text:
            return
        with self._lock:
            if self._stream.closed:
                return
            self._rotate_if_needed(text)
            self._stream.write(text)
            self._stream.flush()

    def flush(self):
        with self._lock:
            if not self._stream.closed:
                self._stream.flush()

    def close(self):
        with self._lock:
            if not self._stream.closed:
                self._stream.close()


class Tee:
    def __init__(self, console, sink):
        self.console = console
        self.sink = sink

    def write(self, text):
        if self.console is not None:
            self.console.write(text)
            self.console.flush()
        self.sink.write(text)

    def flush(self):
        if self.console is not None:
            self.console.flush()
        self.sink.flush()


def configure_windows_app_id():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "clc-corporation.boostify.app.1"
        )
    except Exception:
        pass


def configure_logging():
    original_stderr = sys.stderr
    try:
        ensure_app_directories()
        sink = RotatingLogSink(LOG_DIR / "gui_debug_log.txt")
    except OSError as error:
        if original_stderr is not None:
            original_stderr.write(f"BoostiFy: логирование в файл отключено: {error}\n")
        return
    atexit.register(sink.close)
    sys.stdout = Tee(sys.stdout, sink)
    sys.stderr = Tee(sys.stderr, sink)


def main():
    configure_windows_app_id()
    configure_logging()
    try:
        ensure_storage_ready(migrate=True)
    except OSError as error:
        print(f"Не удалось подготовить каталог данных: {error}", file=sys.stderr)

    from PyQt6.QtWidgets import QApplication

    from BoostiFy.GUI.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
