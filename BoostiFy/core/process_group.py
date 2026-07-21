"""Привязка дочерних runtime-процессов к Windows Job Object.

Зачем: при штатном закрытии GUI гасит боостеры через closeEvent. Но если GUI
падает, зависает или его снимают из диспетчера задач, closeEvent не срабатывает —
и процессы буста остаются сиротами, продолжая эмулировать активность до истечения
своего --exit-after (в скользящем режиме это до 7 суток).

Job Object с флагом KILL_ON_JOB_CLOSE решает это на уровне ОС: пока GUI жив, он
держит единственный ненаследуемый хэндл джоба. Процесс GUI завершается ЛЮБЫМ
способом (штатно, падение, taskkill) → ОС закрывает хэндл → джоб закрывается →
все приписанные процессы убиваются немедленно.

Вне Windows или при любой ошибке WinAPI — тихий no-op: буст работает как прежде.
Хэндл джоба намеренно не закрывается за время жизни процесса: его закрытие и есть
сигнал «убить всех», поэтому его освобождает только выход самого GUI.
"""

import os
import threading

_lock = threading.Lock()
_job_handle = None
_available = os.name == "nt"

if _available:
    import ctypes
    from ctypes import wintypes

    _JobObjectExtendedLimitInformation = 9
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # restype/argtypes обязательны: без них ctypes считает HANDLE 32-битным int и
    # обрезает указатель на 64-битном GUI, приписывая процесс к мусорному хэндлу.
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]


def _ensure_job():
    """Создаёт джоб один раз. Возвращает хэндл (int) или None при сбое."""
    global _job_handle
    if _job_handle is not None:
        return _job_handle
    handle = _kernel32.CreateJobObjectW(None, None)
    if not handle:
        return None
    info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    ok = _kernel32.SetInformationJobObject(
        handle,
        _JobObjectExtendedLimitInformation,
        ctypes.byref(info),
        ctypes.sizeof(info),
    )
    if not ok:
        return None
    _job_handle = handle
    return handle


def track(process):
    """Приписать subprocess.Popen к общему джобу. Best-effort, ошибки проглатываем.

    Windows 8+ разрешает вложенные джобы, поэтому вызов срабатывает, даже если GUI
    уже сам запущен под чьим-то джобом (песочница, некоторые лаунчеры)."""
    if not _available:
        return False
    handle = getattr(process, "_handle", None)
    if handle is None:
        return False
    try:
        with _lock:
            job = _ensure_job()
            if not job:
                return False
            return bool(_kernel32.AssignProcessToJobObject(job, int(handle)))
    except OSError:
        return False
