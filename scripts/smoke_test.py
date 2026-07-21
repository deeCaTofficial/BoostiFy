import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from BoostiFy.core.runtime_paths import (  # noqa: E402
    BACKGROUND_WORKER,
    OWNERSHIP_WORKER,
    RUNTIME_BUILD_SCRIPT,
    STEAM_RUNTIME_LIBRARY,
)


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print(f"[OK] {message}")


def compile_python():
    count = 0
    for path in PROJECT_ROOT.rglob("*.py"):
        if any(part in {".git", "__pycache__", "bin", "obj"} for part in path.parts):
            continue
        source = path.read_text(encoding="utf-8-sig")
        compile(source, str(path), "exec")
        count += 1
    check(count > 0, f"Python files parse cleanly ({count})")


def import_modules():
    modules = [
        "BoostiFy.core.booster",
        "BoostiFy.core.steam_lookup",
        "BoostiFy.GUI.core.game_storage",
        "BoostiFy.GUI.screens.table_widget",
        "BoostiFy.GUI.screens.main_screen",
        "BoostiFy.GUI.screens.settings_screen",
        "BoostiFy.GUI.main_window",
    ]
    for module in modules:
        __import__(module)
    check(True, f"Core modules import cleanly ({len(modules)})")


def validate_json_files():
    from BoostiFy.GUI.core.game_storage import UPLOAD_DIR, ensure_storage_ready

    ensure_storage_ready(migrate=False)
    upload_dir = Path(UPLOAD_DIR)
    count = 0
    for path in upload_dir.glob("*.json"):
        json.loads(path.read_text(encoding="utf-8-sig"))
        count += 1
    check(True, f"Upload JSON files are valid ({count})")


def instantiate_gui():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from BoostiFy.GUI.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    check(window.stacked_widget.count() == 2, "MainWindow creates two screens")
    window.close()
    app.quit()


def check_steam_lookup():
    from BoostiFy.core.steam_lookup import SteamAppLookup

    lookup = SteamAppLookup(allow_fetch=False)
    lookup.apps = [
        {"appid": 10, "name": "Counter-Strike"},
        {"appid": 570, "name": "Dota 2"},
    ]
    lookup._rebuild_index()
    check(lookup.find_appid("Counter-Strike") == 10, "Steam app lookup resolves exact fixture names")
    check(len(lookup.find_similar("Counter", limit=3)) > 0, "Steam app lookup returns similar names")


def check_runtime_binaries(required=False, check_steam=False):
    missing = [
        path for path in (OWNERSHIP_WORKER, BACKGROUND_WORKER, STEAM_RUNTIME_LIBRARY)
        if not path.exists()
    ]
    if missing:
        message = "Runtime is not built: " + ", ".join(path.name for path in missing)
        if required:
            raise AssertionError(message)
        print(f"[SKIP] {message}")
        return
    check(True, "All runtime binaries exist")
    result = subprocess.run(
        [str(OWNERSHIP_WORKER)],
        cwd=str(OWNERSHIP_WORKER.parent),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=15,
    )
    check(result.returncode != 0 and "Usage:" in result.stdout, "Worker responds to missing AppID with usage")

    self_test = subprocess.run(
        [str(OWNERSHIP_WORKER), "--self-test"],
        cwd=str(OWNERSHIP_WORKER.parent),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=15,
    )
    check(self_test.returncode == 0 and "SELF_TEST_OK" in self_test.stdout, "Steam schema self-test passes")

    if not check_steam:
        print("[SKIP] Live Steam ownership protocol (use --steam)")
        return

    server_result = subprocess.run(
        [str(OWNERSHIP_WORKER), "--server"],
        cwd=str(OWNERSHIP_WORKER.parent),
        input="0\n10\nBATCH 0\nexit\n",
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15,
    )
    stdout_lines = [line.strip() for line in server_result.stdout.splitlines() if line.strip()]
    protocol_ok = (
        len(stdout_lines) >= 4
        and stdout_lines[0] == "READY"
        and stdout_lines[1] == "INVALID"
        and stdout_lines[2] in {"OWNED", "NOT_OWNED"}
        and stdout_lines[3] == "OWNED"
    )
    check(protocol_ok, "Server protocol is clean and invokes the owned-app service")


def build_runtime():
    result = subprocess.run(
        [sys.executable, str(RUNTIME_BUILD_SCRIPT)],
        cwd=str(PROJECT_ROOT),
        timeout=240,
    )
    check(result.returncode == 0, "Runtime build script exits successfully")


def main():
    parser = argparse.ArgumentParser(description="Run non-destructive BoostiFy smoke checks.")
    parser.add_argument("--build", action="store_true", help="build the C# runtime before checks")
    parser.add_argument("--require-runtime", action="store_true", help="fail if runtime binaries are missing")
    parser.add_argument("--steam", action="store_true", help="run the live Steam ownership protocol")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="boostify-smoke-") as temp_dir:
        os.environ["BOOSTIFY_DATA_DIR"] = temp_dir
        compile_python()
        import_modules()
        validate_json_files()
        check_steam_lookup()
        if args.build:
            build_runtime()
        instantiate_gui()
        check_runtime_binaries(required=args.require_runtime or args.build, check_steam=args.steam)


if __name__ == "__main__":
    main()
