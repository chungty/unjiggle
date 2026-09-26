"""Data models for Unjiggle layout representation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class WidgetSize(Enum):
    SMALL = "small"       # 2x2 icons
    MEDIUM = "medium"     # 4x2 icons
    LARGE = "large"       # 4x4 icons: the largest widget on iPhone
    EXTRA_LARGE = "extraLarge"  # the iPad family; counted as the largest iPhone size

    @property
    def slots(self) -> int:
        """The icon slots that the widget takes on a page of 24 (6 rows of 4)."""
        return {"small": 4, "medium": 8, "large": 16, "extraLarge": 16}[self.value]

    @classmethod
    def parse(cls, value) -> WidgetSize:
        """The size for an icon state gridSize. A size that is not known counts as the
        largest, so that a page never gets more items than it can show."""
        if value is None:
            return cls.SMALL
        try:
            return cls(value)
        except ValueError:
            return cls.LARGE


@dataclass
class AppItem:
    """An icon on the home screen that opens an app.

    ``pinned`` is True for an icon that is not an App Store app: the icon state gives
    it no bundleIdentifier, only a displayIdentifier (such as a web shortcut or an App
    Clip). ``bundle_id`` is then its displayIdentifier. The App Library cannot hold it,
    so a pinned icon never leaves the home screen: no operation moves or removes it,
    and a rebuild of the pages keeps it (see analyzer.stays_in_rebuild).
    """

    bundle_id: str
    display_name: str | None = None
    category: str | None = None
    icon_url: str | None = None
    icon_data: bytes | None = None
    last_updated: str | None = None
    description: str | None = None
    pinned: bool = False


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

    def pinned_ids(self) -> set[str]:
        """The IDs of the pinned icons (AppItem.pinned) in the dock, on the pages and in
        folders. An ID that an App Store app on the home screen also has is not in the
        set: an operation that names that ID acts on the app."""
        pinned: set[str] = set()
        apps: set[str] = set()
        for page in [self.dock, *self.pages]:
            for item in page:
                members = [item.app] if item.is_app else (
                    [app for folder_page in item.folder.pages for app in folder_page] if item.is_folder else []
                )
                for app in members:
                    (pinned if app.pinned else apps).add(app.bundle_id)
        return pinned - apps

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
