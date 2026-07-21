import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from BoostiFy.core.runtime_paths import missing_runtime_files  # noqa: E402


def main():
    missing = missing_runtime_files()
    if missing:
        print("[ERROR] Build runtime first. Missing: " + ", ".join(path.name for path in missing))
        return 1
    try:
        result = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "BoostiFy.spec"],
            cwd=PROJECT_ROOT,
            timeout=600,
        )
    except subprocess.TimeoutExpired:
        print("[ERROR] Packaging timed out.")
        return 1
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
