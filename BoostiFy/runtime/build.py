import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


RUNTIME_ROOT = Path(__file__).resolve().parent
SOLUTION = RUNTIME_ROOT / "Boostify.Runtime.sln"
WORKER_PROJECT = RUNTIME_ROOT / "Worker" / "Boostify.Runtime.Worker.csproj"
WORKER_OUTPUT = RUNTIME_ROOT / "Worker" / "bin" / "x86" / "Release" / "net48"
BACKGROUND_OUTPUT = RUNTIME_ROOT / "Worker" / "bin" / "x86" / "ReleaseNoConsole" / "net48"


def build_environment():
    environment = os.environ.copy()
    environment.setdefault("DOTNET_CLI_UI_LANGUAGE", "en")
    return environment


def stop_runtime_processes():
    """Stops runtime executables that could lock the output directory."""
    print("Stopping active runtime processes...")
    for process_name in ("Boostify.Worker.exe", "Boostify.Booster.exe"):
        subprocess.run(
            ["taskkill", "/IM", process_name, "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def run_build(target, configuration):
    try:
        return subprocess.run(
            [
                "dotnet",
                "build",
                str(target),
                "-c",
                configuration,
                "-p:Platform=x86",
                "/nr:false",
            ],
            cwd=RUNTIME_ROOT,
            env=build_environment(),
            timeout=600,
        ).returncode
    except FileNotFoundError:
        print("[ERROR] dotnet SDK was not found in PATH.")
        return 1
    except subprocess.TimeoutExpired:
        print(f"[ERROR] Build timed out: {target} ({configuration}).")
        return 1


def publish_background_worker():
    source_executable = BACKGROUND_OUTPUT / "Boostify.Booster.exe"
    target_executable = WORKER_OUTPUT / "Boostify.Booster.exe"
    if not source_executable.exists():
        print(f"[ERROR] Background worker was not produced: {source_executable}")
        return False

    WORKER_OUTPUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_executable, target_executable)

    source_config = source_executable.with_name(source_executable.name + ".config")
    if source_config.exists():
        shutil.copy2(
            source_config,
            target_executable.with_name(target_executable.name + ".config"),
        )

    steam_library = WORKER_OUTPUT / "Boostify.Runtime.Steam.dll"
    if not steam_library.exists():
        print(f"[ERROR] Steam runtime library is missing: {steam_library}")
        return False

    print(f"[OK] Runtime output: {WORKER_OUTPUT}")
    return True


def build_runtime(force_stop=False):
    if not SOLUTION.exists() or not WORKER_PROJECT.exists():
        print("[ERROR] Runtime solution is incomplete.")
        return 1

    if force_stop:
        stop_runtime_processes()
    print("Building Boostify runtime (Release/x86)...")
    result = run_build(SOLUTION, "Release")
    if result != 0:
        return result

    print("Building background worker (ReleaseNoConsole/x86)...")
    result = run_build(WORKER_PROJECT, "ReleaseNoConsole")
    if result != 0:
        return result

    if not publish_background_worker():
        return 1

    steam_path = Path(os.environ.get("SteamInstallPath", r"C:\Program Files (x86)\Steam"))
    if not (steam_path / "steamclient.dll").exists():
        print("[WARN] Steam client was not found in the default location.")

    print("[OK] Boostify runtime build completed.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the isolated BoostiFy runtime.")
    parser.add_argument(
        "--force-stop",
        action="store_true",
        help="force-stop running Boostify workers before building",
    )
    arguments = parser.parse_args()
    sys.exit(build_runtime(force_stop=arguments.force_stop))
