# https://packaging.python.org/en/latest/specifications/inline-script-metadata/
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "requests",
#   "rich",
#   "beautifulsoup4",
#   "httpx",
#   "textual",
# ]
# ///
import requests
from rich import print
from bs4 import BeautifulSoup
import sys
from rich.table import Table
from rich.prompt import Prompt
from datetime import datetime, timedelta
import json
import httpx
import asyncio
from pathlib import Path
from textual.app import ComposeResult, App
from textual.containers import Container, Vertical
from textual.widgets import DataTable, Footer, Header
from textual.binding import Binding


# Cache management
CACHE_DIR = Path.home() / ".cache" / "tide"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_SECONDS = 3600  # 1 hour


def get_cache_file(package_name: str) -> Path:
    """Get the cache file path for a package."""
    return CACHE_DIR / f"{package_name}.json"


def get_cached_release_time(package_name: str) -> tuple[float, str] | None:
    """Get cached release time if it exists and is not expired."""
    cache_file = get_cache_file(package_name)
    if not cache_file.exists():
        return None

    try:
        with open(cache_file) as f:
            data = json.load(f)
        cache_timestamp = data.get("cache_timestamp", 0)
        if datetime.now().timestamp() - cache_timestamp < CACHE_TTL_SECONDS:
            return (data.get("release_timestamp"), data.get("release_display"))
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


def save_release_time_cache(
    package_name: str, release_data: tuple[float, str]
):
    """Save release time to cache."""
    cache_file = get_cache_file(package_name)
    release_timestamp, release_display = release_data
    with open(cache_file, "w") as f:
        json.dump(
            {
                "cache_timestamp": datetime.now().timestamp(),
                "release_timestamp": release_timestamp,
                "release_display": release_display,
            },
            f,
        )


def get_packages(url) -> list[str]:
    # Send a GET request to the webpage with a custom user agent
    headers = {"User-Agent": "python/request/jupyter"}
    response = requests.get(url, headers=headers, allow_redirects=True)

    if response.status_code != 200:
        print(f"Failed to retrieve the webpage. Status code: {response.status_code}")
        exit(1)

    if "A required part of this site couldn’t load" in response.text:
        print(f"Fastly is blocking us for {url}. Status code: 403")
        print(
            "You can try `Array.from(document.querySelectorAll('h3')).map(h3 => h3.innerText).join('\n');`, from js console when viewing a page from a browser and use the `--packages` option."
        )
        print("past result")
        packages = []
        while res := input():
            if not res:
                break
            packages.append(res.split(" ")[0])

        if packages:
            print(f"received {len(packages)} packages")
            return packages
        exit(1)

    # Parse the HTML content
    soup = BeautifulSoup(response.content, "html.parser")

    # Find all <h3> tags and accumulate their text in a list
    h3_tags = [h3.get_text(strip=True) for h3 in soup.find_all("h3")]

    # Sort the list of <h3> contents
    h3_tags.sort()

    if not h3_tags:
        print("No packages found")
        exit(1)
    return h3_tags


async def get_last_release_time(
    client: httpx.AsyncClient, package_name: str
) -> tuple[float, str]:
    """Get timestamp and human-readable time since last release for a package.

    Returns: (timestamp_seconds, human_readable_string)
    """
    # Check cache first
    cached = get_cached_release_time(package_name)
    if cached is not None:
        return cached

    try:
        response = await client.get(
            f"https://pypi.org/pypi/{package_name}/json", timeout=5
        )
        response.raise_for_status()
        data = response.json()

        releases = data["releases"]
        if not releases:
            result = (float("inf"), "unknown")
        else:
            # Find the most recent release by actual upload date, not version number
            latest_upload_time = None
            for version, files in releases.items():
                if not files:
                    continue
                upload_time = files[0]["upload_time_iso_8601"]
                if latest_upload_time is None or upload_time > latest_upload_time:
                    latest_upload_time = upload_time

            if not latest_upload_time:
                result = (float("inf"), "unknown")
            else:
                release_dt = datetime.fromisoformat(
                    latest_upload_time.replace("Z", "+00:00")
                )
                now = datetime.now(release_dt.tzinfo)
                delta = now - release_dt
                timestamp = release_dt.timestamp()

                days = delta.days
                if days == 0:
                    human_readable = "today"
                elif days == 1:
                    human_readable = "1 day ago"
                elif days < 30:
                    human_readable = f"{days} days ago"
                elif days < 365:
                    months = days // 30
                    human_readable = f"{months}m ago"
                else:
                    years = days // 365
                    remaining_days = days % 365
                    months = remaining_days // 30

                    parts = []
                    parts.append(f"{years}y")
                    if months > 0:
                        parts.append(f"{months}m")

                    human_readable = ", ".join(parts) + " ago"

                result = (timestamp, human_readable)

        save_release_time_cache(package_name, result)
        return result
    except (httpx.RequestError, KeyError, IndexError, ValueError):
        return (float("inf"), "unknown")


async def fetch_release_times(
    packages: list[str],
) -> dict[str, tuple[float, str]]:
    """Fetch release times for multiple packages concurrently.

    Returns: dict mapping package name to (timestamp, human_readable_string)
    """
    release_times = {}

    async with httpx.AsyncClient() as client:

        async def fetch_with_client(name):
            release_times[name] = await get_last_release_time(client, name)

        # Create tasks for all packages and run concurrently
        tasks = [fetch_with_client(name) for name in packages]
        await asyncio.gather(*tasks)

    return release_times


async def get_tidelift_data(packages, only_liftable=False):
    """Fetch tidelift data and return enriched package information."""
    packages_data = [{"platform": "pypi", "name": h3} for h3 in packages]

    data = {"packages": packages_data}
    res = requests.post(
        "https://tidelift.com/api/depci/estimate/bulk_estimates", json=data
    )

    res.raise_for_status()

    # Collecting all package data
    package_data = []
    response_data = res.json()

    for package in response_data:
        name = package["name"]
        lifted = package["lifted"]
        estimated_money = package["estimated_money"]
        package_data.append((name, lifted, estimated_money))

    package_names = {p["name"] for p in response_data}
    for package in packages:
        if package not in package_names:
            package_data.append((package, None, None))

    def maybefloat(x):
        if x is None:
            return 0
        try:
            return float(x)
        except TypeError:
            return 0

    # Fetch release times for all packages
    packages_to_fetch = [name for name, _, _ in package_data]
    release_times = await fetch_release_times(packages_to_fetch)

    # Build final data list
    result = []
    for name, lifted, estimated_money in package_data:
        if only_liftable and estimated_money is None:
            continue

        release_timestamp, release_display = release_times.get(
            name, (float("inf"), "unknown")
        )
        result.append(
            {
                "name": name,
                "lifted": lifted,
                "estimated_money": estimated_money,
                "last_release": release_display,
                "last_release_timestamp": release_timestamp,
            }
        )

    return result


def print_table(data: list[dict]) -> None:
    """Print package data as a rich table."""
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#")
    table.add_column("Package Name")
    table.add_column("Url")
    table.add_column("Estimated Money")
    table.add_column("Lifted")
    table.add_column("Last Release")

    def maybefloat(x):
        if x is None:
            return 0
        try:
            return float(x)
        except TypeError:
            return 0

    # Sort: lifted True first, then None, then False, then by money, then by name
    sorted_data = sorted(
        data,
        key=lambda x: (
            x["lifted"] is None,
            x["lifted"] is False,
            -maybefloat(x["estimated_money"]),
            x["name"],
        ),
    )

    for i, item in enumerate(sorted_data, start=1):
        lifted_str = (
            "✓"
            if item["lifted"] is True
            else "✗"
            if item["lifted"] is False
            else "-"
        )
        money_str = (
            str(item["estimated_money"])
            if item["estimated_money"] is not None
            else "--"
        )
        table.add_row(
            str(i),
            item["name"],
            f"https://pypi.org/project/{item['name']}",
            money_str,
            f"[green]{lifted_str}[/green]" if lifted_str == "✓" else f"[red]{lifted_str}[/red]",
            item["last_release"],
        )

    print(table)


class TideApp(App):
    """Textual app for viewing Tidelift package data."""

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "sort_lifted", "Sort by Lifted"),
        Binding("m", "sort_money", "Sort by Money"),
        Binding("n", "sort_name", "Sort by Name"),
        Binding("l", "sort_release", "Sort by Release"),
    ]

    def __init__(self, packages: list[str], only_liftable: bool):
        super().__init__()
        self.packages = packages
        self.only_liftable = only_liftable
        self.data = []
        self.sort_column = None
        self.sort_reverse = False

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Header()
        yield DataTable(id="packages-table")
        yield Footer()

    async def on_mount(self) -> None:
        """Load data when app starts."""
        table = self.query_one(DataTable)
        # Add columns once
        table.add_column("Package Name", key="name")
        table.add_column("Lifted", key="lifted")
        table.add_column("Estimated Money", key="estimated_money")
        table.add_column("Last Release", key="last_release")
        await self.load_data()

    async def load_data(self) -> None:
        """Load package data from API."""
        self.data = await get_tidelift_data(self.packages, self.only_liftable)
        self.populate_table()

    def populate_table(self) -> None:
        """Populate the data table."""
        table = self.query_one(DataTable)
        # Clear only rows, not columns
        table.clear(columns=False)

        # Sort data
        sorted_data = self.get_sorted_data()

        # Add rows
        for item in sorted_data:
            lifted_str = (
                "✓" if item["lifted"] is True else "✗" if item["lifted"] is False else "-"
            )
            money_str = (
                str(item["estimated_money"])
                if item["estimated_money"] is not None
                else "--"
            )
            table.add_row(
                item["name"],
                lifted_str,
                money_str,
                item["last_release"],
            )

    def get_sorted_data(self) -> list[dict]:
        """Get sorted package data."""

        def maybefloat(x):
            if x is None:
                return 0
            try:
                return float(x)
            except (TypeError, ValueError):
                return 0

        if self.sort_column == "lifted":
            sorted_data = sorted(
                self.data,
                key=lambda x: (
                    x["lifted"] is None,
                    x["lifted"] is False,
                    x["name"],
                ),
                reverse=self.sort_reverse,
            )
        elif self.sort_column == "money":
            sorted_data = sorted(
                self.data,
                key=lambda x: (maybefloat(x["estimated_money"]), x["name"]),
                reverse=not self.sort_reverse,
            )
        elif self.sort_column == "release":
            # Sort by release timestamp (much simpler!)
            sorted_data = sorted(
                self.data,
                key=lambda x: (x["last_release_timestamp"], x["name"]),
                reverse=not self.sort_reverse,
            )
        else:
            # Default sort: by lifted, then money, then name
            sorted_data = sorted(
                self.data,
                key=lambda x: (
                    x["lifted"] is None,
                    x["lifted"] is False,
                    -maybefloat(x["estimated_money"]),
                    x["name"],
                ),
            )

        return sorted_data

    def action_sort_lifted(self) -> None:
        """Sort by lifted status."""
        if self.sort_column == "lifted":
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = "lifted"
            self.sort_reverse = False
        self.populate_table()

    def action_sort_money(self) -> None:
        """Sort by estimated money."""
        if self.sort_column == "money":
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = "money"
            self.sort_reverse = False
        self.populate_table()

    def action_sort_name(self) -> None:
        """Sort by package name."""
        if self.sort_column == "name":
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = "name"
            self.sort_reverse = False
        self.populate_table()

    def action_sort_release(self) -> None:
        """Sort by last release time."""
        if self.sort_column == "release":
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = "release"
            self.sort_reverse = False
        self.populate_table()


if __name__ == "__main__":
    # URL of the webpage
    args = sys.argv[1:]
    packages = []
    only_liftable = False
    use_app = False
    while args:
        if args[0] == "--org":
            url = f"https://pypi.org/org/{args[1]}/"
            packages += get_packages(url)
            args = args[2:]
        elif args[0] == "--user":
            url = f"https://pypi.org/user/{args[1]}/"
            packages += get_packages(url)
            args = args[2:]
        elif args[0] == "--packages":
            packages += args[1:]
            args = []
        elif args[0] == "--only-liftable":
            only_liftable = True
            args = args[1:]
        elif args[0] == "--app":
            use_app = True
            args = args[1:]
        else:
            print(
                "Invalid argument. Please use either --org ORG, --user USER or --packages PACKAGE1 PACKAGE2 ... [--only-liftable] [--app]"
            )
            exit(1)

    async def main():
        return await get_tidelift_data(packages, only_liftable=only_liftable)

    if use_app:
        app = TideApp(packages, only_liftable)
        app.run()
    else:
        data = asyncio.run(main())
        print_table(data)
