from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PACKAGE_ROOT / "runtime"
WORKER_OUTPUT = RUNTIME_ROOT / "Worker" / "bin" / "x86" / "Release" / "net48"

OWNERSHIP_WORKER = WORKER_OUTPUT / "Boostify.Worker.exe"
BACKGROUND_WORKER = WORKER_OUTPUT / "Boostify.Booster.exe"
STEAM_RUNTIME_LIBRARY = WORKER_OUTPUT / "Boostify.Runtime.Steam.dll"
RUNTIME_BUILD_SCRIPT = RUNTIME_ROOT / "build.py"


def required_runtime_files():
    return (OWNERSHIP_WORKER, BACKGROUND_WORKER, STEAM_RUNTIME_LIBRARY)


def missing_runtime_files():
    return [path for path in required_runtime_files() if not path.is_file()]


def runtime_is_ready() -> bool:
    return not missing_runtime_files()
