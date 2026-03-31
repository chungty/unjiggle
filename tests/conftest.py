"""Shared test fixtures for Unjiggle."""

import pytest

from unjiggle.models import (
    AppItem,
    FolderItem,
    HomeScreenLayout,
    LayoutItem,
    WidgetItem,
    WidgetSize,
)


def make_app(bundle_id: str) -> LayoutItem:
    return LayoutItem(app=AppItem(bundle_id=bundle_id))


def make_folder(name: str, apps: list[str]) -> LayoutItem:
    return LayoutItem(folder=FolderItem(
        display_name=name,
        pages=[[AppItem(bundle_id=bid) for bid in apps]],
    ))


def make_widget(bundle_id: str, size: WidgetSize = WidgetSize.SMALL) -> LayoutItem:
    return LayoutItem(widget=WidgetItem(
        container_bundle_id=bundle_id,
        grid_size=size,
    ))


@pytest.fixture
def chaotic_layout() -> HomeScreenLayout:
    """A realistic messy layout: 7 pages, mixed categories, bad folders."""
    return HomeScreenLayout(
        dock=[
            make_app("com.apple.mobilesafari"),
            make_app("com.apple.MobileSMS"),
            make_app("com.custom.obscure-app"),
            make_app("com.apple.mobilephone"),
        ],
        pages=[
            # Page 1: mixed bag (social, work, utilities)
            [
                make_app("com.apple.Maps"),
                make_app("com.google.calendar"),
                make_app("com.apple.mobilephone"),
                make_app("com.apple.weather"),
                make_app("com.spotify.client"),
                make_folder("Social", [
                    "com.facebook.Facebook",
                    "com.linkedin.LinkedIn",
                    "com.twitter.twitter",
                    "com.whatsapp.WhatsApp",
                ]),
                make_app("com.apple.AppStore"),
                make_app("com.apple.Preferences"),
                make_app("com.tinyspeck.chatlyio"),  # Slack
                make_app("com.apple.facetime"),
                make_app("com.notion.Notion"),
                make_app("com.salesforce.chatter"),
                make_app("com.google.Google"),
                make_app("com.apple.Wallet"),
                make_app("com.apple.mobilenotes"),
                make_app("com.agilebits.onepassword"),
            ],
            # Page 2: more mixed
            [
                make_app("com.netflix.Netflix"),
                make_app("com.amazon.Amazon"),
                make_app("com.apple.mobileslideshow"),
                make_app("com.instagram.Instagram"),
                make_app("com.google.chrome.ios"),
                make_app("com.uber.UberClient"),
                make_app("com.lyft.ios"),
                make_app("com.venmo.Venmo"),
                make_app("com.robinhood.release.Robinhood"),
                make_app("com.reddit.Reddit"),
                make_app("com.zhiliaoapp.musically"),  # TikTok
                make_app("com.youtube.YouTube"),
            ],
            # Page 3: developer tools mixed with random
            [
                make_app("com.github.stormbreaker.prod"),
                make_app("com.apple.dt.Xcode"),
                make_app("com.microsoft.VSCode"),
                make_app("com.termius.Termius"),
                make_app("com.adobe.lightroomcc"),
                make_app("com.figma.FigmaMirror"),
                make_app("com.nike.onenikecommerce"),
                make_app("com.peloton.PelotonCycle"),
                make_app("com.strava.stravaride"),
                make_app("com.headspace.headspace"),
                make_app("com.calm.calm"),
                make_app("com.myfitnesspal.mfp"),
            ],
            # Page 4: kids apps + random
            [
                make_app("com.disney.disneyplus"),
                make_app("com.pbskids.PBSKids"),
                make_app("com.lego.duplo.world"),
                make_app("com.sago.SagoMini.Babies"),
                make_app("com.apple.podcasts"),
                make_app("com.airbnb.app"),
                make_app("com.booking.BookingApp"),
                make_app("com.delta.DeltaAssistant"),
                make_app("com.expedia.app"),
                make_app("com.tripadvisor.TripAdvisorNA"),
            ],
            # Page 5: junk drawer (barely used)
            [
                make_app("com.hp.printer"),
                make_app("com.canon.print"),
                make_app("com.epson.iprintphoto"),
                make_folder("L BV", ["com.uber.UberEats", "com.doordash.DoorDash"]),
                make_folder("VDG FLOW", ["com.trello.trello", "com.atlassian.jira"]),
                make_app("com.adt.pulse"),
                make_app("com.ring.ring"),
                make_app("com.nest.jasper"),
            ],
            # Page 6: more junk
            [
                make_app("com.darksky.darksky"),
                make_app("com.carrotweather.CARROT"),
                make_app("com.theweathernetwork.weathereye"),
                make_app("com.duolingo.Duolingo"),
                make_app("com.babbel.Babbel"),
                make_app("com.rosettastone.streak"),
            ],
            # Page 7: basically forgotten
            [
                make_app("com.ibm.watson.ios"),
                make_app("com.shazam.Shazam"),
                make_app("com.soundhound.SoundHound"),
            ],
        ],
        ignored=["com.apple.tips", "com.apple.clips", "com.apple.iMovie"],
    )


@pytest.fixture
def clean_layout() -> HomeScreenLayout:
    """A well-organized layout for comparison."""
    return HomeScreenLayout(
        dock=[
            make_app("com.apple.mobilephone"),
            make_app("com.apple.MobileSMS"),
            make_app("com.apple.mobilesafari"),
            make_app("com.apple.mobilemail"),
        ],
        pages=[
            # Page 1: daily essentials
            [
                make_app("com.apple.Maps"),
                make_app("com.apple.weather"),
                make_app("com.apple.mobileslideshow"),
                make_app("com.apple.camera"),
                make_app("com.spotify.client"),
                make_app("com.apple.mobilenotes"),
                make_app("com.apple.Preferences"),
                make_app("com.apple.AppStore"),
            ],
            # Page 2: social
            [
                make_app("com.instagram.Instagram"),
                make_app("com.twitter.twitter"),
                make_app("com.facebook.Facebook"),
                make_app("com.whatsapp.WhatsApp"),
                make_app("com.reddit.Reddit"),
                make_app("com.youtube.YouTube"),
            ],
        ],
        ignored=[],
    )


@pytest.fixture
def sample_metadata() -> dict[str, dict]:
    """Metadata for apps in chaotic_layout."""
    return {
        "com.apple.Maps": {"name": "Maps", "genre": "Navigation", "super_category": "Travel", "icon_url": None, "last_updated": None, "description": None},
        "com.google.calendar": {"name": "Google Calendar", "genre": "Productivity", "super_category": "Productivity", "icon_url": None, "last_updated": None, "description": None},
        "com.apple.weather": {"name": "Weather", "genre": "Weather", "super_category": "Utilities", "icon_url": None, "last_updated": None, "description": None},
        "com.spotify.client": {"name": "Spotify", "genre": "Music", "super_category": "Entertainment", "icon_url": None, "last_updated": None, "description": None},
        "com.tinyspeck.chatlyio": {"name": "Slack", "genre": "Business", "super_category": "Productivity", "icon_url": None, "last_updated": None, "description": None},
        "com.notion.Notion": {"name": "Notion", "genre": "Productivity", "super_category": "Productivity", "icon_url": None, "last_updated": None, "description": None},
        "com.salesforce.chatter": {"name": "Salesforce", "genre": "Business", "super_category": "Productivity", "icon_url": None, "last_updated": None, "description": None},
        "com.netflix.Netflix": {"name": "Netflix", "genre": "Entertainment", "super_category": "Entertainment", "icon_url": None, "last_updated": None, "description": None},
        "com.instagram.Instagram": {"name": "Instagram", "genre": "Photo & Video", "super_category": "Social", "icon_url": None, "last_updated": None, "description": None},
        "com.uber.UberClient": {"name": "Uber", "genre": "Travel", "super_category": "Travel", "icon_url": None, "last_updated": None, "description": None},
        "com.github.stormbreaker.prod": {"name": "GitHub", "genre": "Developer Tools", "super_category": "Productivity", "icon_url": None, "last_updated": None, "description": None},
        "com.nike.onenikecommerce": {"name": "Nike", "genre": "Shopping", "super_category": "Shopping", "icon_url": None, "last_updated": None, "description": None},
        "com.peloton.PelotonCycle": {"name": "Peloton", "genre": "Health & Fitness", "super_category": "Health", "icon_url": None, "last_updated": None, "description": None},
        "com.strava.stravaride": {"name": "Strava", "genre": "Health & Fitness", "super_category": "Health", "icon_url": None, "last_updated": None, "description": None},
        "com.headspace.headspace": {"name": "Headspace", "genre": "Health & Fitness", "super_category": "Health", "icon_url": None, "last_updated": None, "description": None},
        "com.calm.calm": {"name": "Calm", "genre": "Health & Fitness", "super_category": "Health", "icon_url": None, "last_updated": None, "description": None},
        "com.disney.disneyplus": {"name": "Disney+", "genre": "Entertainment", "super_category": "Entertainment", "icon_url": None, "last_updated": None, "description": None},
        "com.darksky.darksky": {"name": "Dark Sky", "genre": "Weather", "super_category": "Utilities", "icon_url": None, "last_updated": "2020-07-01", "description": "Hyperlocal weather forecasts"},
        "com.carrotweather.CARROT": {"name": "CARROT Weather", "genre": "Weather", "super_category": "Utilities", "icon_url": None, "last_updated": "2025-11-01", "description": "Talking weather app"},
        "com.theweathernetwork.weathereye": {"name": "Weather Network", "genre": "Weather", "super_category": "Utilities", "icon_url": None, "last_updated": None, "description": None},
        "com.duolingo.Duolingo": {"name": "Duolingo", "genre": "Education", "super_category": "Education", "icon_url": None, "last_updated": None, "description": "Language learning"},
        "com.hp.printer": {"name": "HP Smart", "genre": "Utilities", "super_category": "Utilities", "icon_url": None, "last_updated": None, "description": None},
        "com.canon.print": {"name": "Canon PRINT", "genre": "Utilities", "super_category": "Utilities", "icon_url": None, "last_updated": None, "description": None},
        "com.epson.iprintphoto": {"name": "Epson iPrint", "genre": "Utilities", "super_category": "Utilities", "icon_url": None, "last_updated": None, "description": None},
        "com.custom.obscure-app": {"name": "Obscure App", "genre": "Utilities", "super_category": "Utilities", "icon_url": None, "last_updated": None, "description": None},
        "com.apple.mobilesafari": {"name": "Safari", "genre": "Utilities", "super_category": "System", "icon_url": None, "last_updated": None, "description": None},
        "com.apple.MobileSMS": {"name": "Messages", "genre": "Social Networking", "super_category": "System", "icon_url": None, "last_updated": None, "description": None},
        "com.apple.mobilephone": {"name": "Phone", "genre": "Utilities", "super_category": "System", "icon_url": None, "last_updated": None, "description": None},
    }
