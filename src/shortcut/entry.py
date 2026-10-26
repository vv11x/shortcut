import logging
import os
import sys
from pathlib import Path

from shortcut.windows_desktop import main as windows_command


def configure_error_log() -> None:
    log_directory = Path(os.environ["LOCALAPPDATA"]) / "shortcut" / "logs"
    log_directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=log_directory / "shortcut.log",
        level=logging.INFO,
        encoding="utf-8",
        format="%(asctime)s %(levelname)s %(message)s",
    )
    default_hook = sys.excepthook

    def log_unhandled(error_type, error, traceback):
        logging.error("Unhandled shortcut error", exc_info=(error_type, error, traceback))
        default_hook(error_type, error, traceback)

    sys.excepthook = log_unhandled


def main() -> int:
    configure_error_log()
    logging.info("shortcut starting")
    try:
        if len(sys.argv) > 1:
            return windows_command(sys.argv[1:])
        from shortcut.app import run_gui

        return run_gui()
    except BaseException:
        logging.exception("shortcut terminated with an unhandled error")
        raise
