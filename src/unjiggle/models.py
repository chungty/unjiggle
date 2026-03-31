"""Data models for Unjiggle layout representation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class WidgetSize(Enum):
    SMALL = "small"       # 2x2
    MEDIUM = "medium"     # 4x2
    EXTRA_LARGE = "extraLarge"  # 4x4


@dataclass
class AppItem:
    bundle_id: str
    display_name: str | None = None
    category: str | None = None
    icon_url: str | None = None
    icon_data: bytes | None = None
    last_updated: str | None = None
    description: str | None = None


@dataclass
class WidgetItem:
    container_bundle_id: str
    grid_size: WidgetSize
    raw: dict = field(default_factory=dict)


@dataclass
class FolderItem:
    display_name: str
    pages: list[list[AppItem]] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class LayoutItem:
    """Union type for items in a page grid."""
    app: AppItem | None = None
    folder: FolderItem | None = None
    widget: WidgetItem | None = None

    @property
    def is_app(self) -> bool:
        return self.app is not None

    @property
    def is_folder(self) -> bool:
        return self.folder is not None

    @property
    def is_widget(self) -> bool:
        return self.widget is not None

    @property
    def label(self) -> str:
        if self.app:
            return self.app.display_name or self.app.bundle_id
        if self.folder:
            return self.folder.display_name
        if self.widget:
            return f"Widget: {self.widget.container_bundle_id}"
        return "Unknown"


@dataclass
class HomeScreenLayout:
    dock: list[LayoutItem] = field(default_factory=list)
    pages: list[list[LayoutItem]] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)  # App Library-only bundle IDs
    raw: dict = field(default_factory=dict)  # Original plist for backup/restore

    @property
    def total_apps(self) -> int:
        count = 0
        for item in self.dock:
            if item.is_app:
                count += 1
            elif item.is_folder:
                count += sum(len(page) for page in item.folder.pages)
        for page in self.pages:
            for item in page:
                if item.is_app:
                    count += 1
                elif item.is_folder:
                    count += sum(len(p) for p in item.folder.pages)
        return count

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def all_bundle_ids(self) -> list[str]:
        """All visible app bundle IDs (home screen, not App Library)."""
        ids = []
        for item in self.dock:
            if item.is_app:
                ids.append(item.app.bundle_id)
            elif item.is_folder:
                for page in item.folder.pages:
                    for app in page:
                        ids.append(app.bundle_id)
        for page in self.pages:
            for item in page:
                if item.is_app:
                    ids.append(item.app.bundle_id)
                elif item.is_folder:
                    for fpage in item.folder.pages:
                        for app in fpage:
                            ids.append(app.bundle_id)
        return ids

    def all_folders(self) -> list[FolderItem]:
        folders = []
        for item in self.dock:
            if item.is_folder:
                folders.append(item.folder)
        for page in self.pages:
            for item in page:
                if item.is_folder:
                    folders.append(item.folder)
        return folders


@dataclass
class DeviceInfo:
    name: str
    model: str
    ios_version: str
    udid: str


@dataclass
class ScoreBreakdown:
    page_efficiency: float    # 0-100
    category_coherence: float  # 0-100
    folder_usage: float       # 0-100
    dock_quality: float       # 0-100

    @property
    def total(self) -> float:
        return (
            self.page_efficiency * 0.30
            + self.category_coherence * 0.30
            + self.folder_usage * 0.20
            + self.dock_quality * 0.20
        )

    @property
    def label(self) -> str:
        score = self.total
        if score <= 25:
            return "Chaotic"
        if score <= 50:
            return "Cluttered"
        if score <= 75:
            return "Getting There"
        if score <= 90:
            return "Well Organized"
        return "Perfectly Tuned"
