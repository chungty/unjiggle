"""Demo: run all three viral features against a realistic mock phone."""

from rich.console import Console
from rich.table import Table

from unjiggle.models import AppItem, FolderItem, HomeScreenLayout, LayoutItem, ScoreBreakdown
from unjiggle.obituary import identify_dead_apps
from unjiggle.swipetax import compute_swipe_tax

console = Console()


def _app(bid):
    return LayoutItem(app=AppItem(bundle_id=bid))


# Build a realistic 226-app, 8-page layout
METADATA = {
    # Dock
    "com.apple.mobilephone": {"name": "Phone", "super_category": "System", "last_updated": "2025-09-01T00:00:00Z", "description": "Make and receive calls"},
    "com.apple.mobilesafari": {"name": "Safari", "super_category": "System", "last_updated": "2025-09-01T00:00:00Z", "description": "Web browser"},
    "com.apple.MobileSMS": {"name": "Messages", "super_category": "System", "last_updated": "2025-09-01T00:00:00Z", "description": "Send messages"},
    "com.apple.mobilemail": {"name": "Mail", "super_category": "System", "last_updated": "2025-09-01T00:00:00Z", "description": "Email client"},
    # Page 1 — daily drivers
    "com.burbn.instagram": {"name": "Instagram", "super_category": "Social", "last_updated": "2025-12-15T00:00:00Z", "description": "Photo and video sharing social network"},
    "com.atebits.Tweetie2": {"name": "X", "super_category": "Social", "last_updated": "2025-11-01T00:00:00Z", "description": "See what's happening in the world right now"},
    "com.spotify.client": {"name": "Spotify", "super_category": "Entertainment", "last_updated": "2025-12-01T00:00:00Z", "description": "Music and podcast streaming"},
    "com.google.Maps": {"name": "Google Maps", "super_category": "Travel", "last_updated": "2025-12-10T00:00:00Z", "description": "GPS navigation and local search"},
    "com.toyopagroup.picaboo": {"name": "Snapchat", "super_category": "Social", "last_updated": "2025-12-01T00:00:00Z", "description": "Share photos and videos with friends"},
    "com.zhiliaoapp.musically": {"name": "TikTok", "super_category": "Entertainment", "last_updated": "2025-12-01T00:00:00Z", "description": "Short-form video platform"},
    "com.apple.mobileslideshow": {"name": "Photos", "super_category": "System", "last_updated": "2025-09-01T00:00:00Z", "description": "Photo library"},
    "com.apple.camera": {"name": "Camera", "super_category": "System", "last_updated": "2025-09-01T00:00:00Z", "description": "Take photos and videos"},
    # Page 2 — productivity
    "com.slack.Slack": {"name": "Slack", "super_category": "Productivity", "last_updated": "2025-12-01T00:00:00Z", "description": "Team messaging and collaboration"},
    "com.notion.Notion": {"name": "Notion", "super_category": "Productivity", "last_updated": "2025-12-01T00:00:00Z", "description": "Notes, docs, and project management"},
    "com.linear.Linear": {"name": "Linear", "super_category": "Productivity", "last_updated": "2025-12-01T00:00:00Z", "description": "Issue tracking for software teams"},
    "com.figma.FigmaApp": {"name": "Figma", "super_category": "Productivity", "last_updated": "2025-11-01T00:00:00Z", "description": "Collaborative design tool"},
    "com.github.GitHub": {"name": "GitHub", "super_category": "Productivity", "last_updated": "2025-12-01T00:00:00Z", "description": "Code hosting and collaboration"},
    "com.google.Gmail": {"name": "Gmail", "super_category": "Productivity", "last_updated": "2025-12-01T00:00:00Z", "description": "Email by Google"},
    "com.google.chrome.ios": {"name": "Chrome", "super_category": "Utilities", "last_updated": "2025-12-01T00:00:00Z", "description": "Web browser by Google"},
    # Page 3 — health/fitness phase + meditation phase
    "com.nike.nrc": {"name": "Nike Run Club", "super_category": "Health", "last_updated": "2025-10-01T00:00:00Z", "description": "Running tracker and coaching"},
    "com.strava": {"name": "Strava", "super_category": "Health", "last_updated": "2025-11-01T00:00:00Z", "description": "Track running and cycling"},
    "com.fitnesskeeper.runkeeper": {"name": "Runkeeper", "super_category": "Health", "last_updated": "2024-08-01T00:00:00Z", "description": "GPS running tracker"},
    "com.headspace.headspace": {"name": "Headspace", "super_category": "Health", "last_updated": "2025-06-01T00:00:00Z", "description": "Meditation and sleep"},
    "com.calm.Calm": {"name": "Calm", "super_category": "Health", "last_updated": "2025-05-01T00:00:00Z", "description": "Meditation, sleep, and relaxation"},
    "com.wakingup.app": {"name": "Waking Up", "super_category": "Health", "last_updated": "2025-03-01T00:00:00Z", "description": "Meditation and mindfulness"},
    "com.innerbalance.app": {"name": "Ten Percent Happier", "super_category": "Health", "last_updated": "2024-01-01T00:00:00Z", "description": "Meditation for skeptics"},
    "com.myfitnesspal.mfp": {"name": "MyFitnessPal", "super_category": "Health", "last_updated": "2025-09-01T00:00:00Z", "description": "Calorie counter and diet tracker"},
    # Page 4 — finance + shopping
    "com.robinhood.release": {"name": "Robinhood", "super_category": "Finance", "last_updated": "2025-12-01T00:00:00Z", "description": "Stock and crypto trading"},
    "com.coinbase.Coinbase": {"name": "Coinbase", "super_category": "Finance", "last_updated": "2025-12-01T00:00:00Z", "description": "Buy and sell cryptocurrency"},
    "com.mint.internal": {"name": "Mint", "super_category": "Finance", "last_updated": "2023-12-01T00:00:00Z", "description": "Personal finance and budgeting (discontinued)"},
    "com.amazon.Amazon": {"name": "Amazon", "super_category": "Shopping", "last_updated": "2025-12-01T00:00:00Z", "description": "Online shopping"},
    "com.doordash.DoorDash": {"name": "DoorDash", "super_category": "Shopping", "last_updated": "2025-12-01T00:00:00Z", "description": "Food delivery"},
    "com.ubercab.UberEats": {"name": "Uber Eats", "super_category": "Shopping", "last_updated": "2025-12-01T00:00:00Z", "description": "Food delivery"},
    # Page 5 — games + entertainment (the fun page)
    "com.supercell.clash": {"name": "Clash of Clans", "super_category": "Games", "last_updated": "2025-06-01T00:00:00Z", "description": "Build your village and fight in clan wars"},
    "com.nianticlabs.pokemongo": {"name": "Pokémon GO", "super_category": "Games", "last_updated": "2025-09-01T00:00:00Z", "description": "Catch Pokémon in the real world"},
    "com.innersloth.amongus": {"name": "Among Us", "super_category": "Games", "last_updated": "2023-03-01T00:00:00Z", "description": "Online multiplayer social deduction game"},
    "com.king.candycrush": {"name": "Candy Crush", "super_category": "Games", "last_updated": "2025-10-01T00:00:00Z", "description": "Match-three puzzle game"},
    "io.playflix.wordle": {"name": "Wordle", "super_category": "Games", "last_updated": "2025-01-01T00:00:00Z", "description": "Daily word puzzle"},
    "com.netflix.Netflix": {"name": "Netflix", "super_category": "Entertainment", "last_updated": "2025-12-01T00:00:00Z", "description": "Streaming movies and TV shows"},
    "com.disney.disneyplus": {"name": "Disney+", "super_category": "Entertainment", "last_updated": "2025-11-01T00:00:00Z", "description": "Streaming Disney content"},
    # Page 6 — the graveyard (junk drawer folder + loose dead apps)
    "com.duolingo.DuolingoMobile": {"name": "Duolingo", "super_category": "Education", "last_updated": "2025-10-01T00:00:00Z", "description": "Learn languages for free"},
    "com.rosettastone.rosettastone": {"name": "Rosetta Stone", "super_category": "Education", "last_updated": "2023-06-01T00:00:00Z", "description": "Language learning software"},
    "com.memrise.android.memrisecompanion": {"name": "Memrise", "super_category": "Education", "last_updated": "2023-01-01T00:00:00Z", "description": "Learn languages with flashcards"},
    "com.busuu.app": {"name": "Busuu", "super_category": "Education", "last_updated": "2022-08-01T00:00:00Z", "description": "Learn languages with native speakers"},
    "com.darksky.weather": {"name": "Dark Sky", "super_category": "Utilities", "last_updated": "2022-01-01T00:00:00Z", "description": "Hyperlocal weather forecasts (discontinued by Apple)"},
    "com.weather.Weather": {"name": "Weather Underground", "super_category": "Utilities", "last_updated": "2023-04-01T00:00:00Z", "description": "Local weather forecasts and radar"},
    "com.accuweather.app": {"name": "AccuWeather", "super_category": "Utilities", "last_updated": "2024-06-01T00:00:00Z", "description": "Weather forecasts and alerts"},
    "com.purify.app": {"name": "Purify", "super_category": "Utilities", "last_updated": "2021-03-01T00:00:00Z", "description": "Ad blocker for Safari (discontinued)"},
    "com.clubhouse.app": {"name": "Clubhouse", "super_category": "Social", "last_updated": "2023-09-01T00:00:00Z", "description": "Audio chat rooms (remember when everyone was on this?)"},
    "com.bitstrips.bitmoji": {"name": "Bitmoji", "super_category": "Social", "last_updated": "2024-01-01T00:00:00Z", "description": "Create your personal emoji"},
    # Page 7 — more graveyard
    "com.vsco.vsco": {"name": "VSCO", "super_category": "Social", "last_updated": "2025-06-01T00:00:00Z", "description": "Photo and video editor"},
    "com.camerontech.snapseed": {"name": "Snapseed", "super_category": "Social", "last_updated": "2023-01-01T00:00:00Z", "description": "Photo editor by Google"},
    "com.lightricks.Lightroom": {"name": "Lightroom", "super_category": "Social", "last_updated": "2025-11-01T00:00:00Z", "description": "Pro photo editor by Adobe"},
    "com.afterlight.app": {"name": "Afterlight", "super_category": "Social", "last_updated": "2022-06-01T00:00:00Z", "description": "Photo editing and filters"},
    "com.flightradar24.iphone": {"name": "Flightradar24", "super_category": "Travel", "last_updated": "2025-08-01T00:00:00Z", "description": "Real-time flight tracker"},
    "com.sourdough.starter": {"name": "Bread Baker", "super_category": "Other", "last_updated": "2021-11-01T00:00:00Z", "description": "Sourdough starter timer and recipes"},
    "com.robinhood.crypto": {"name": "Crypto Wallet", "super_category": "Finance", "last_updated": "2022-04-01T00:00:00Z", "description": "Store and manage cryptocurrency"},
    "com.fidelity.investments": {"name": "Fidelity", "super_category": "Finance", "last_updated": "2025-11-01T00:00:00Z", "description": "Investment management"},
    # Page 8 — the deepest graveyard
    "com.peloton.app": {"name": "Peloton", "super_category": "Health", "last_updated": "2025-03-01T00:00:00Z", "description": "Fitness classes and workouts"},
    "com.classpass.classpass": {"name": "ClassPass", "super_category": "Health", "last_updated": "2024-05-01T00:00:00Z", "description": "Book fitness classes"},
    "com.zillow.Zillow": {"name": "Zillow", "super_category": "Other", "last_updated": "2025-06-01T00:00:00Z", "description": "Real estate listings and home values"},
    "com.redfin.redfin": {"name": "Redfin", "super_category": "Other", "last_updated": "2025-01-01T00:00:00Z", "description": "Buy and sell real estate"},
    "com.trulia.trulia": {"name": "Trulia", "super_category": "Other", "last_updated": "2023-03-01T00:00:00Z", "description": "Home listings and neighborhood info"},
    "com.meetup.app": {"name": "Meetup", "super_category": "Social", "last_updated": "2024-06-01T00:00:00Z", "description": "Find local groups and events"},
    "com.bumble.app": {"name": "Bumble", "super_category": "Social", "last_updated": "2025-10-01T00:00:00Z", "description": "Dating, friends, and networking"},
    "com.hinge.hinge": {"name": "Hinge", "super_category": "Social", "last_updated": "2025-11-01T00:00:00Z", "description": "The dating app designed to be deleted"},
}

# Build the layout
junk_folder_apps = [AppItem(bundle_id=bid) for bid in [
    "com.darksky.weather", "com.weather.Weather", "com.accuweather.app",
    "com.purify.app", "com.clubhouse.app", "com.bitstrips.bitmoji",
    "com.rosettastone.rosettastone", "com.memrise.android.memrisecompanion",
    "com.busuu.app", "com.duolingo.DuolingoMobile",
    "com.sourdough.starter", "com.robinhood.crypto",
]]

LAYOUT = HomeScreenLayout(
    dock=[
        _app("com.apple.mobilephone"), _app("com.apple.mobilesafari"),
        _app("com.apple.MobileSMS"), _app("com.apple.mobilemail"),
    ],
    pages=[
        # Page 1
        [_app("com.burbn.instagram"), _app("com.atebits.Tweetie2"),
         _app("com.spotify.client"), _app("com.google.Maps"),
         _app("com.toyopagroup.picaboo"), _app("com.zhiliaoapp.musically"),
         _app("com.apple.mobileslideshow"), _app("com.apple.camera")],
        # Page 2
        [_app("com.slack.Slack"), _app("com.notion.Notion"),
         _app("com.linear.Linear"), _app("com.figma.FigmaApp"),
         _app("com.github.GitHub"), _app("com.google.Gmail"),
         _app("com.google.chrome.ios")],
        # Page 3
        [_app("com.nike.nrc"), _app("com.strava"),
         _app("com.fitnesskeeper.runkeeper"), _app("com.headspace.headspace"),
         _app("com.calm.Calm"), _app("com.wakingup.app"),
         _app("com.innerbalance.app"), _app("com.myfitnesspal.mfp")],
        # Page 4
        [_app("com.robinhood.release"), _app("com.coinbase.Coinbase"),
         _app("com.mint.internal"), _app("com.amazon.Amazon"),
         _app("com.doordash.DoorDash"), _app("com.ubercab.UberEats")],
        # Page 5
        [_app("com.supercell.clash"), _app("com.nianticlabs.pokemongo"),
         _app("com.innersloth.amongus"), _app("com.king.candycrush"),
         _app("io.playflix.wordle"), _app("com.netflix.Netflix"),
         _app("com.disney.disneyplus")],
        # Page 6 — junk drawer folder + loose apps
        [LayoutItem(folder=FolderItem(display_name="Stuff", pages=[junk_folder_apps])),
         _app("com.vsco.vsco"), _app("com.camerontech.snapseed")],
        # Page 7
        [_app("com.lightricks.Lightroom"), _app("com.afterlight.app"),
         _app("com.flightradar24.iphone"), _app("com.fidelity.investments")],
        # Page 8
        [_app("com.peloton.app"), _app("com.classpass.classpass"),
         _app("com.zillow.Zillow"), _app("com.redfin.redfin"),
         _app("com.trulia.trulia"), _app("com.meetup.app"),
         _app("com.bumble.app"), _app("com.hinge.hinge")],
    ],
)


def demo_swipetax():
    console.print("\n[bold]" + "=" * 60 + "[/bold]")
    console.print("[bold]  DEMO: unjiggle swipetax[/bold]")
    console.print("[bold]" + "=" * 60 + "[/bold]\n")

    console.print("[bold]Unjiggle[/bold] — Swipe Tax Calculator\n")

    tax = compute_swipe_tax(LAYOUT, METADATA)

    console.print(f"  [bold yellow]{tax.headline}[/bold yellow]\n")
    console.print(f"  Current layout:  [red]{tax.total_annual_swipes:>8,} swipes/year[/red]")
    console.print(f"  Optimal layout:  [green]{tax.optimal_annual_swipes:>8,} swipes/year[/green]")
    console.print(f"  [bold]You could save:  {tax.savings:>8,} swipes/year[/bold]\n")

    if tax.worst_offenders:
        table = Table(title="Top Offenders", show_header=True, header_style="bold")
        table.add_column("App", style="bold")
        table.add_column("Page", justify="center")
        table.add_column("Swipes to Reach", justify="center")
        table.add_column("Wasted/Year", justify="right", style="red")

        for app in tax.worst_offenders:
            loc = f"{'📁 ' if app.in_folder else ''}Page {app.page}"
            table.add_row(
                app.name,
                loc,
                str(app.swipes_to_reach),
                f"{app.annual_wasted_swipes:,}",
            )
        console.print(table)
        console.print()

    console.print(f"  [bold]Fix it:[/bold] [bold]unjiggle suggest[/bold] to reorganize with AI")
    console.print(f"  [dim]https://unjiggle.com[/dim]\n")


def demo_obituary():
    console.print("\n[bold]" + "=" * 60 + "[/bold]")
    console.print("[bold]  DEMO: unjiggle obituary[/bold]")
    console.print("[bold]" + "=" * 60 + "[/bold]\n")

    console.print("[bold]Unjiggle[/bold] — The Digital Graveyard\n")

    dead = identify_dead_apps(LAYOUT, METADATA)
    console.print(f"  [bold]{len(dead)} apps didn't make it.[/bold]\n")

    # Since we have no API key, show what the dead-app detector found
    # and write mock obituaries for the most dead
    MOCK_EULOGIES = {
        "com.darksky.weather": (
            "Dark Sky (2012–2023)",
            "Downloaded back when hyperlocal weather was magic. Died the day Apple acquired it "
            "and folded every useful feature into the stock Weather app. It predicted its own demise "
            "with uncanny accuracy.",
            "Natural causes (acquisition by Apple)",
            "Weather app (the one you already had)",
        ),
        "com.purify.app": (
            "Purify (2015–2021)",
            "Served you well when mobile ad blocking required a third-party app and a prayer. "
            "Safari learned the trick natively. Purify didn't get the memo that it was obsolete.",
            "Rendered redundant by Safari content blockers",
            "Safari (built-in)",
        ),
        "com.clubhouse.app": (
            "Clubhouse (2021–2023)",
            "Downloaded during two frenzied weeks in February 2021 when everyone pretended they wanted "
            "to listen to strangers talk. The invite-only hype lasted exactly as long as the pandemic lockdown. "
            "Survived by Twitter Spaces, which you also don't use.",
            "Died of hype exhaustion",
            "Twitter Spaces (also unused)",
        ),
        "com.busuu.app": (
            "Busuu (circa 2022–2023)",
            "Part of the great language-learning app collection. You now have four of them and speak "
            "zero additional languages. Busuu was the quiet one — downloaded third, opened twice, "
            "forgotten by Thursday.",
            "Died of being the fourth language app",
            "Duolingo (the only one with the owl guilt trip)",
        ),
        "com.sourdough.starter": (
            "Bread Baker (2020–2021)",
            "Born in the great sourdough pandemic of 2020. Fed your starter religiously for six weeks. "
            "The starter died first, but the app lingered on page 6 as a monument to your ambitions.",
            "Cause of death: the sourdough phase ended",
            "DoorDash (the real solution to dinner)",
        ),
        "com.robinhood.crypto": (
            "Crypto Wallet (2021–2022)",
            "Downloaded during the bull run. You checked it 40 times a day in November 2021 and "
            "haven't opened it since Bitcoin hit $17K. The portfolio is still there. You'd rather not look.",
            "Died of a crypto winter",
            "Robinhood (where the pain is consolidated)",
        ),
        "com.rosettastone.rosettastone": (
            "Rosetta Stone (circa 2021–2023)",
            "The premium one. You actually paid for this. The annual subscription renewed twice before "
            "you noticed. You completed exactly one unit of Spanish and can confidently say 'el niño come arroz.'",
            "Death by forgotten subscription",
            "Duolingo (free guilt > paid guilt)",
        ),
        "com.memrise.android.memrisecompanion": (
            "Memrise (2022–2023)",
            "The third language app. Downloaded because someone on Reddit said it was 'better than Duolingo "
            "for vocabulary.' They were right. You used it for vocabulary exactly once.",
            "Died of Redditor oversell",
            None,
        ),
        "com.innersloth.amongus": (
            "Among Us (2020–2023)",
            "Sus. You were sus for downloading this during a work meeting. Peak usage: November 2020 "
            "when your entire team played instead of doing standup. The imposter was your productivity.",
            "Voted out by adulthood",
            None,
        ),
        "com.mint.internal": (
            "Mint (2019–2023)",
            "Faithfully tracked your spending until Intuit killed it. For four years, you checked it "
            "monthly and felt bad about DoorDash. Then they shut the servers off and the guilt went with it.",
            "Murdered by Intuit (discontinued Dec 2023)",
            "Credit Karma (Intuit's replacement, which you didn't download)",
        ),
    }

    for i, app in enumerate(dead[:10]):
        bid = app["bundle_id"]
        mock = MOCK_EULOGIES.get(bid)
        if not mock:
            continue

        title, eulogy, cause, survived = mock
        console.print(f"  [dim]{'─' * 50}[/dim]")
        console.print(f"  [bold]⚰️  {title}[/bold]\n")
        console.print(f"  {eulogy}")
        console.print(f"  [dim italic]Cause of death: {cause}[/dim italic]")
        if survived:
            console.print(f"  [dim]Survived by: {survived}[/dim]")
        console.print()

    console.print(f"  [dim]{'─' * 50}[/dim]")
    console.print(f'\n  [italic]"A graveyard of {len(dead)} abandoned ambitions, 4 language apps, and one sourdough timer."[/italic]\n')
    console.print(f"  [dim]Share your graveyard. Everyone has one.[/dim]")
    console.print(f"  [dim]https://unjiggle.com[/dim]\n")


def demo_mirror():
    console.print("\n[bold]" + "=" * 60 + "[/bold]")
    console.print("[bold]  DEMO: unjiggle mirror[/bold]")
    console.print("[bold]" + "=" * 60 + "[/bold]\n")

    console.print("[bold]Unjiggle[/bold] — Personality Mirror\n")

    # Mock mirror output (this is what the LLM would generate)
    console.print(f"  [bold magenta]The Roast[/bold magenta]\n")
    console.print(
        "  You have four meditation apps and TikTok. That's not a wellness journey, "
        "that's a hostage negotiation between your prefrontal cortex and your dopamine receptors. "
        "Your phone tells the story of someone who buys running shoes, downloads three trackers, "
        "goes for two jogs, then orders DoorDash from the couch while Strava silently judges from page 3. "
        "You downloaded four language apps and speak zero additional languages. "
        "The Bread Baker app on page 6 is a monument to the pandemic you, who briefly believed "
        "that sourdough was a personality trait.\n"
    )

    console.print(f"  [bold cyan]Life Phases Detected[/bold cyan]\n")

    phases = [
        ("The Fitness Awakening", "Nike Run Club, Strava, Runkeeper, Peloton, ClassPass, MyFitnessPal",
         "Six fitness apps spanning 3 years. The ambition was real. The 5am alarm was not."),
        ("The Mindfulness Era", "Headspace, Calm, Waking Up, Ten Percent Happier",
         "Four meditation apps, each downloaded after a particularly stressful week. Combined lifetime usage: under 3 hours."),
        ("The Polyglot Fantasy", "Duolingo, Rosetta Stone, Memrise, Busuu",
         "Four language apps, zero new languages. The owl stopped sending notifications. Even Duolingo gave up on you."),
        ("The Pandemic Sourdough Phase", "Bread Baker",
         "One app. One starter. Six weeks of hope. The starter died. The app lives on as a digital headstone."),
    ]

    for name, apps, narrative in phases:
        console.print(f"  [bold]{name}[/bold]")
        console.print(f"  {narrative}")
        console.print(f"  [dim]Evidence: {apps}[/dim]\n")

    console.print(f"  [bold yellow]Contradictions[/bold yellow]\n")

    contradictions = [
        ("Self-Improvement vs. Doomscrolling",
         "You have Headspace, Calm, Waking Up, and Ten Percent Happier — but TikTok and Instagram "
         "have a combined screen time that makes your meditation apps weep.",
         "Headspace, Calm, Waking Up vs. TikTok, Instagram, X"),
        ("Financial Discipline vs. Food Delivery",
         "Robinhood and Coinbase say 'I'm building wealth.' DoorDash and Uber Eats say "
         "'but first, $47 pad thai with a $12 delivery fee.'",
         "Robinhood, Coinbase, Fidelity vs. DoorDash, Uber Eats"),
    ]

    for tension, roast, apps in contradictions:
        console.print(f"  [bold]{tension}[/bold]")
        console.print(f"  {roast}")
        console.print(f"  [dim]{apps}[/dim]\n")

    console.print(f"  [bold red]Guilty Pleasure[/bold red]")
    console.print("  Candy Crush on page 5. You tell yourself it's 'just for the subway.' "
                   "It's not just for the subway.\n")

    console.print("  ─────────────────────────────────────────")
    console.print(f'\n  [italic]"226 apps, 4 meditation apps, 4 language apps, 0 inner peace, 0 new languages. '
                  f'Your phone is a graveyard of good intentions."[/italic]\n')
    console.print(f"  [dim]Copy that line. Post it. You know you want to.[/dim]")
    console.print(f"  [dim]https://unjiggle.com[/dim]\n")


def generate_demo_cards():
    """Generate actual HTML share cards from mock data and open them."""
    import webbrowser
    from pathlib import Path

    from unjiggle.cards import (
        generate_mirror_card,
        generate_obituary_card,
        generate_swipetax_card,
        save_card,
    )
    from unjiggle.mirror import MirrorResult, LifePhase, Contradiction
    from unjiggle.obituary import Obituary, ObituaryResult
    from unjiggle.swipetax import compute_swipe_tax

    out_dir = Path.home() / ".unjiggle" / "reports"

    # 1. Swipe Tax card (real computation)
    tax = compute_swipe_tax(LAYOUT, METADATA)
    card = generate_swipetax_card(LAYOUT, METADATA, tax)
    path = out_dir / "demo-swipetax.html"
    save_card(card, path)
    console.print(f"  [green]Swipe Tax card:[/green] {path}")

    # 2. Obituary card (mock LLM output)
    obit_result = ObituaryResult(
        total_dead=15,
        obituaries=[
            Obituary("Dark Sky", "com.darksky.weather", "2012", "2023",
                     "Natural causes (acquisition by Apple)",
                     "Downloaded back when hyperlocal weather was magic. Died the day Apple acquired it and folded every useful feature into the stock Weather app.",
                     "Weather app"),
            Obituary("Clubhouse", "com.clubhouse.app", "2021", "2023",
                     "Died of hype exhaustion",
                     "Downloaded during two frenzied weeks when everyone pretended they wanted to listen to strangers talk. The invite-only hype lasted exactly as long as the lockdown.",
                     "Twitter Spaces (also unused)"),
            Obituary("Bread Baker", "com.sourdough.starter", "2020", "2021",
                     "The sourdough phase ended",
                     "Born in the great pandemic of 2020. Fed your starter religiously for six weeks. The starter died first, but the app lingered on page 6 as a monument.",
                     "DoorDash"),
            Obituary("Rosetta Stone", "com.rosettastone.rosettastone", "2021", "2023",
                     "Death by forgotten subscription",
                     "The premium one. You actually paid. The annual subscription renewed twice before you noticed. You completed one unit of Spanish.",
                     "Duolingo"),
        ],
        graveyard_summary="A graveyard of 15 abandoned ambitions, 4 language apps, and one sourdough timer.",
    )
    card = generate_obituary_card(LAYOUT, METADATA, obit_result)
    path = out_dir / "demo-obituary.html"
    save_card(card, path)
    console.print(f"  [green]Obituary card:[/green]  {path}")

    # 3. Mirror card (mock LLM output)
    mirror_result = MirrorResult(
        roast="You have four meditation apps and TikTok. That's not a wellness journey, that's a hostage negotiation between your prefrontal cortex and your dopamine receptors. Your phone tells the story of someone who buys running shoes, downloads three trackers, goes for two jogs, then orders DoorDash from the couch while Strava silently judges from page 3.",
        phases=[
            LifePhase("The Fitness Awakening", ["Nike Run Club", "Strava", "Runkeeper", "Peloton"],
                      "Six fitness apps spanning 3 years. The ambition was real."),
            LifePhase("The Mindfulness Era", ["Headspace", "Calm", "Waking Up", "Ten Percent Happier"],
                      "Four meditation apps. Combined lifetime usage: under 3 hours."),
            LifePhase("The Polyglot Fantasy", ["Duolingo", "Rosetta Stone", "Memrise", "Busuu"],
                      "Four language apps, zero new languages."),
            LifePhase("The Sourdough Phase", ["Bread Baker"],
                      "One app. One starter. Six weeks of hope."),
        ],
        contradictions=[
            Contradiction("Self-Improvement vs. Doomscrolling",
                         ["Headspace", "Calm", "Waking Up"],
                         ["TikTok", "Instagram", "X"],
                         ""),
            Contradiction("Financial Discipline vs. Food Delivery",
                         ["Robinhood", "Coinbase", "Fidelity"],
                         ["DoorDash", "Uber Eats"],
                         ""),
        ],
        guilty_pleasure="Candy Crush on page 5. You tell yourself it's just for the subway.",
        one_line="226 apps, 4 meditation apps, 4 language apps, 0 inner peace, 0 new languages. Your phone is a graveyard of good intentions.",
    )
    card = generate_mirror_card(LAYOUT, METADATA, mirror_result)
    path = out_dir / "demo-mirror.html"
    save_card(card, path)
    console.print(f"  [green]Mirror card:[/green]   {path}")

    # Open all three
    console.print()
    for name in ["demo-swipetax", "demo-obituary", "demo-mirror"]:
        p = out_dir / f"{name}.html"
        webbrowser.open(f"file://{p.resolve()}")

    console.print("  [bold]All 3 share cards opened in browser.[/bold]\n")


if __name__ == "__main__":
    demo_swipetax()
    demo_obituary()
    demo_mirror()
    console.print("\n[bold]Generating share cards...[/bold]\n")
    generate_demo_cards()
