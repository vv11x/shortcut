import json
import os
from pathlib import Path

from shortcut.models import AppSettings


DATA_DIRECTORY = Path(os.environ["LOCALAPPDATA"]) / "shortcut"
SETTINGS_FILE = DATA_DIRECTORY / "settings.json"


def load_settings() -> AppSettings:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    if SETTINGS_FILE.exists():
        return AppSettings.from_dict(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
    return AppSettings.defaults()


def save_settings(settings: AppSettings) -> None:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps(settings.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
