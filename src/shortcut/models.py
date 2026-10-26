from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4


def path_key(path: Path) -> str:
    return str(path.resolve()).casefold()


@dataclass
class CategoryRule:
    extensions: list[str] = field(default_factory=list)
    name_terms: list[str] = field(default_factory=list)
    item_kinds: list[str] = field(default_factory=list)
    mode: str = "any"

    def matches(self, path: Path) -> bool:
        if self.mode not in ("any", "all"):
            raise ValueError(f"Unsupported rule mode: {self.mode}")
        checks: list[bool] = []
        suffix = path.suffix.casefold()
        if self.extensions:
            checks.append(suffix in {value.casefold() for value in self.extensions})
        if self.name_terms:
            name = path.name.casefold()
            checks.append(any(value.casefold() in name for value in self.name_terms))
        if self.item_kinds:
            kinds = {
                "folder": path.is_dir(),
                "file": path.is_file(),
                "application": suffix in {".exe", ".lnk", ".url", ".appref-ms"},
            }
            checks.append(any(kinds[value] for value in self.item_kinds))
        if not checks:
            return False
        if self.mode == "all":
            return all(checks)
        return any(checks)

    def to_dict(self) -> dict:
        return {
            "extensions": self.extensions,
            "name_terms": self.name_terms,
            "item_kinds": self.item_kinds,
            "mode": self.mode,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "CategoryRule":
        return cls(
            extensions=list(value["extensions"]),
            name_terms=list(value["name_terms"]),
            item_kinds=list(value["item_kinds"]),
            mode=value["mode"],
        )


@dataclass
class Category:
    id: str
    title: str
    icon: str
    rule: CategoryRule = field(default_factory=CategoryRule)

    @classmethod
    def create(cls, title: str, icon: str = "other") -> "Category":
        return cls(id=uuid4().hex, title=title, icon=icon)

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "icon": self.icon, "rule": self.rule.to_dict()}

    @classmethod
    def from_dict(cls, value: dict) -> "Category":
        return cls(
            id=value["id"],
            title=value["title"],
            icon=value["icon"],
            rule=CategoryRule.from_dict(value["rule"]),
        )


@dataclass(frozen=True)
class ShortcutEntry:
    path: Path

    @property
    def key(self) -> str:
        return path_key(self.path)

    @property
    def title(self) -> str:
        return self.path.stem if self.path.is_file() else self.path.name


@dataclass
class AppSettings:
    dock_edge: str = "bottom"
    display_mode: str = "dock"
    view_mode: str = "icons"
    theme: str = "dark"
    categories: list[Category] = field(default_factory=list)
    manual_assignments: dict[str, str] = field(default_factory=dict)
    entry_orders: dict[str, list[str]] = field(default_factory=dict)
    category_positions: dict[str, list[int]] = field(default_factory=dict)
    dismissed_paths: list[str] = field(default_factory=list)
    fixed_paths: list[str] = field(default_factory=list)
    archiver_path: str = ""

    @classmethod
    def defaults(cls) -> "AppSettings":
        return cls(
            categories=[
                Category("applications", "应用", "apps", CategoryRule(item_kinds=["application"])),
                Category(
                    "documents",
                    "文档",
                    "documents",
                    CategoryRule(extensions=[".doc", ".docx", ".pdf", ".txt", ".md", ".xls", ".xlsx", ".ppt", ".pptx"]),
                ),
                Category(
                    "pictures",
                    "图片",
                    "images",
                    CategoryRule(extensions=[".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"]),
                ),
                Category("folders", "文件夹", "folders", CategoryRule(item_kinds=["folder"])),
                Category("archives", "压缩包", "archives", CategoryRule(extensions=[".zip", ".7z", ".rar", ".tar", ".gz"])),
                Category(
                    "media",
                    "影音",
                    "media",
                    CategoryRule(extensions=[".mp3", ".wav", ".flac", ".mp4", ".mkv", ".mov", ".avi"]),
                ),
                Category("other", "其他", "other"),
            ]
        )

    def to_dict(self) -> dict:
        return {
            "schema_version": 1,
            "dock_edge": self.dock_edge,
            "display_mode": self.display_mode,
            "view_mode": self.view_mode,
            "theme": self.theme,
            "categories": [category.to_dict() for category in self.categories],
            "manual_assignments": self.manual_assignments,
            "entry_orders": self.entry_orders,
            "category_positions": self.category_positions,
            "dismissed_paths": self.dismissed_paths,
            "fixed_paths": self.fixed_paths,
            "archiver_path": self.archiver_path,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "AppSettings":
        if value["schema_version"] != 1:
            raise ValueError(f"Unsupported settings schema: {value['schema_version']}")
        settings = cls(
            dock_edge=value["dock_edge"],
            display_mode=value["display_mode"],
            view_mode=value["view_mode"],
            theme=value["theme"],
            categories=[Category.from_dict(item) for item in value["categories"]],
            manual_assignments=dict(value["manual_assignments"]),
            entry_orders={key: list(paths) for key, paths in value["entry_orders"].items()},
            category_positions={key: [int(value) for value in position] for key, position in value["category_positions"].items()},
            dismissed_paths=list(value["dismissed_paths"]),
            fixed_paths=list(value["fixed_paths"]),
            archiver_path=value["archiver_path"],
        )
        if not settings.categories:
            raise ValueError("Settings must contain at least one category")
        return settings
