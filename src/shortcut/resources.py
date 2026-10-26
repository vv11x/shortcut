import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
ASSETS_ROOT = PROJECT_ROOT / "assets"


def _required_asset(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def category_icon(name: str) -> Path:
    return _required_asset(ASSETS_ROOT / "icons" / "shortcut-moe-v1" / "icons" / f"{name}.png")


def mascot_image() -> Path:
    return _required_asset(ASSETS_ROOT / "branding" / "shortcut-mascot.png")


def character_sheet() -> Path:
    return _required_asset(ASSETS_ROOT / "branding" / "shortcut-mascot-turnaround.png")


def category_icons() -> list[tuple[str, str]]:
    manifest = json.loads((ASSETS_ROOT / "icons" / "shortcut-moe-v1" / "manifest.json").read_text(encoding="utf-8"))
    return [(key, manifest["names"][key]) for key in manifest["icons"]]
