import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths

from shortcut.models import AppSettings, Category, ShortcutEntry, path_key


class DesktopCatalog:
    def __init__(self, settings: AppSettings):
        self.settings = settings
        self.entries: list[ShortcutEntry] = []
        self.groups: dict[str, list[ShortcutEntry]] = {}
        self.uncategorized: list[ShortcutEntry] = []

    def refresh(self) -> None:
        desktop = Path(QStandardPaths.writableLocation(QStandardPaths.DesktopLocation))
        public_desktop = Path(os.environ["PUBLIC"]) / "Desktop"
        paths: dict[str, Path] = {}
        for root in (desktop, public_desktop):
            for path in root.iterdir():
                paths[path_key(path)] = path
        for value in self.settings.fixed_paths:
            path = Path(value)
            if path.exists():
                paths[path_key(path)] = path

        self.entries = [ShortcutEntry(path) for path in sorted(paths.values(), key=lambda item: item.name.casefold())]
        self.groups = {category.id: [] for category in self.settings.categories}
        self.uncategorized = []
        dismissed = {path_key(Path(value)) for value in self.settings.dismissed_paths}

        for entry in self.entries:
            if entry.key in dismissed:
                continue
            category_id = self.settings.manual_assignments.get(entry.key)
            if category_id:
                self.groups[category_id].append(entry)
                continue
            category = next((item for item in self.settings.categories if item.rule.matches(entry.path)), None)
            if category is None:
                category = next((item for item in self.settings.categories if item.id == "other"), None)
            if category:
                self.groups[category.id].append(entry)
            else:
                self.uncategorized.append(entry)

        for category in self.settings.categories:
            order = {path_key(Path(value)): index for index, value in enumerate(self.settings.entry_orders.get(category.id, []))}
            self.groups[category.id].sort(
                key=lambda entry: (order.get(entry.key, len(order)), entry.path.name.casefold())
            )

    def entries_for(self, category: Category) -> list[ShortcutEntry]:
        return self.groups[category.id]

    def search(self, text: str) -> list[ShortcutEntry]:
        terms = [term.casefold() for term in text.split()]
        dismissed = {path_key(Path(value)) for value in self.settings.dismissed_paths}
        return [
            entry
            for entry in self.entries
            if entry.key not in dismissed
            and all(term in entry.path.name.casefold() or term in str(entry.path).casefold() for term in terms)
        ]
