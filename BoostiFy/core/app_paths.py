import os
import shutil
from pathlib import Path


APP_NAME = "BoostiFy"
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PACKAGE_ROOT.parent
LEGACY_DATA_DIR = PACKAGE_ROOT / "upload"


def _default_data_dir() -> Path:
    override = os.environ.get("BOOSTIFY_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / APP_NAME


DATA_DIR = _default_data_dir()
LOG_DIR = DATA_DIR / "logs"


def ensure_app_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def migrate_legacy_data(destination: Path | None = None) -> list[str]:
    """Copy legacy runtime data once, without overwriting newer user files."""
    target = Path(destination or DATA_DIR)
    target.mkdir(parents=True, exist_ok=True)
    if not LEGACY_DATA_DIR.is_dir() or LEGACY_DATA_DIR.resolve() == target.resolve():
        return []

    migrated = []
    for name in (
        "config.json",
        "user_games.json",
        "games_upload.json",
        "black_list.json",
        "white_list.json",
    ):
        source = LEGACY_DATA_DIR / name
        destination_file = target / name
        if source.is_file() and not destination_file.exists():
            try:
                shutil.copy2(source, destination_file)
                migrated.append(name)
            except OSError:
                continue

    source_configs = LEGACY_DATA_DIR / "configs"
    destination_configs = target / "configs"
    if source_configs.is_dir() and not destination_configs.exists():
        try:
            shutil.copytree(source_configs, destination_configs)
            migrated.append("configs/")
        except OSError:
            pass
    return migrated
