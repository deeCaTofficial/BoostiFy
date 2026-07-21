import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main():
    environment = os.environ.copy()
    # Global pytest plugins from unrelated software must not affect this project.
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "pytest", *sys.argv[1:]],
        cwd=PROJECT_ROOT,
        env=environment,
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
