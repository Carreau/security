# https://packaging.python.org/en/latest/specifications/inline-script-metadata/
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "rich",
#   "beautifulsoup4",
#   "httpx",
#   "textual",
#   "playwright",
#   "typer",
# ]
# ///
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
from textual.widgets import DataTable, Footer, Header, Input
from textual.binding import Binding
from rich.text import Text
import typer
from typing import Optional, List


# Cache management
CACHE_DIR = Path.home() / ".cache" / "tide"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_SECONDS = 3600  # 1 hour


def get_cache_file(package_name: str, type: str = "release") -> Path:
    """Get the cache file path for a package.

    type can be 'release' or 'pypi'
    """
    return CACHE_DIR / f"{package_name}_{type}.json"


def get_cached_release_time(package_name: str) -> tuple[float, str] | None:
    """Get cached release time if it exists and is not expired."""
    cache_file = get_cache_file(package_name, type="release")
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
    cache_file = get_cache_file(package_name, type="release")
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


def get_cached_pypi_response(package_name: str) -> dict | None:
    """Get cached PyPI response if it exists and is not expired."""
    cache_file = get_cache_file(package_name, type="pypi")
    if not cache_file.exists():
        return None

    try:
        with open(cache_file) as f:
            data = json.load(f)
        cache_timestamp = data.get("cache_timestamp", 0)
        if datetime.now().timestamp() - cache_timestamp < CACHE_TTL_SECONDS:
            pypi_data = data.get("pypi_data")
            if pypi_data:
                return pypi_data
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


def save_pypi_response_cache(package_name: str, pypi_data: dict):
    """Save PyPI response to cache."""
    cache_file = get_cache_file(package_name, type="pypi")
    with open(cache_file, "w") as f:
        json.dump(
            {
                "cache_timestamp": datetime.now().timestamp(),
                "pypi_data": pypi_data,
            },
            f,
        )


def get_packages_cache(url: str) -> list[str] | None:
    """Get cached package list from URL."""
    cache_key = url.replace("/", "_").replace(":", "")
    cache_file = CACHE_DIR / f"packages_{cache_key}.json"
    if not cache_file.exists():
        return None

    try:
        with open(cache_file) as f:
            data = json.load(f)
        timestamp = data.get("cache_timestamp", 0)
        if datetime.now().timestamp() - timestamp < CACHE_TTL_SECONDS:
            return data.get("packages")
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def save_packages_cache(url: str, packages: list[str]):
    """Save package list to cache."""
    cache_key = url.replace("/", "_").replace(":", "")
    cache_file = CACHE_DIR / f"packages_{cache_key}.json"
    with open(cache_file, "w") as f:
        json.dump(
            {
                "cache_timestamp": datetime.now().timestamp(),
                "packages": packages,
            },
            f,
        )


def get_top_packages_cache(limit: int) -> list[str] | None:
    """Get cached top packages list."""
    cache_file = CACHE_DIR / "top_packages.json"
    if not cache_file.exists():
        return None

    try:
        with open(cache_file) as f:
            data = json.load(f)
        timestamp = data.get("cache_timestamp", 0)
        if datetime.now().timestamp() - timestamp < CACHE_TTL_SECONDS:
            packages = data.get("packages")
            if packages and len(packages) >= limit:
                return packages[:limit]
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def save_top_packages_cache(packages: list[str]):
    """Save top packages list to cache."""
    cache_file = CACHE_DIR / "top_packages.json"
    with open(cache_file, "w") as f:
        json.dump(
            {
                "cache_timestamp": datetime.now().timestamp(),
                "packages": packages,
            },
            f,
        )


def get_tidelift_cache(packages: list[str]) -> list[dict] | None:
    """Get cached Tidelift data for a set of packages."""
    import hashlib
    # Create a cache key from sorted package names
    cache_key = hashlib.md5("_".join(sorted(packages)).encode()).hexdigest()
    cache_file = CACHE_DIR / f"tidelift_{cache_key}.json"

    if not cache_file.exists():
        return None

    try:
        with open(cache_file) as f:
            data = json.load(f)
        timestamp = data.get("cache_timestamp", 0)
        if datetime.now().timestamp() - timestamp < CACHE_TTL_SECONDS:
            return data.get("data")
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def save_tidelift_cache(packages: list[str], data: list[dict]):
    """Save Tidelift data to cache."""
    import hashlib
    cache_key = hashlib.md5("_".join(sorted(packages)).encode()).hexdigest()
    cache_file = CACHE_DIR / f"tidelift_{cache_key}.json"

    with open(cache_file, "w") as f:
        json.dump(
            {
                "cache_timestamp": datetime.now().timestamp(),
                "data": data,
            },
            f,
        )


async def get_packages_with_playwright(url: str) -> list[str] | None:
    """Try to fetch packages using Playwright (handles JavaScript)."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    try:
        async with async_playwright() as p:
            # Use chromium in headless mode
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            # Set a realistic user agent
            await page.set_extra_http_headers(
                {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                }
            )
            await page.goto(url, wait_until="networkidle")
            # Wait a bit for any dynamic content
            await page.wait_for_timeout(1000)
            content = await page.content()
            await browser.close()

            soup = BeautifulSoup(content, "html.parser")
            # Look for h3 tags that are package names (typically have a link or specific structure)
            h3_tags = []
            for h3 in soup.find_all("h3"):
                text = h3.get_text(strip=True)
                # Package names should not have spaces and are typically lowercase or start with letter
                # Filter out headers like "Projects" or other non-package h3s
                # Also filter out archived or special indicators
                if (
                    text
                    and len(text) > 0
                    and not text.isupper()
                    and "Archived" not in text
                    and "archived" not in text
                ):
                    h3_tags.append(text)
            h3_tags.sort()

            return h3_tags if h3_tags else None
    except Exception as e:
        error_str = str(e).lower()
        if "executable" in error_str or "browser" in error_str or "not found" in error_str:
            print(
                "\n  Playwright browser binaries not found. Installing..."
            )
            import subprocess
            try:
                # Try to install chromium
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=True,
                    timeout=120,
                )
                print("  Chromium installed. Retrying fetch...")
                # Retry
                return await get_packages_with_playwright(url)
            except Exception as install_error:
                print(f"\n  Failed to auto-install browsers: {install_error}")
                print("  Try manually installing with:")
                print("    uv run playwright install chromium\n")
        else:
            print(f"  Playwright error: {e}\n")
        return None


async def get_top_packages(limit: int = 500) -> list[str]:
    """Fetch the top N most downloaded PyPI packages."""
    # Check cache first
    cached = get_top_packages_cache(limit)
    if cached:
        print(f"Using cached top {limit} packages")
        return cached

    print(f"Fetching top {limit} most downloaded PyPI packages...")
    try:
        # Use the publicly maintained top PyPI packages list (contains 15000 packages)
        url = "https://hugovk.github.io/top-pypi-packages/top-pypi-packages.min.json"
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
        all_packages = [pkg["project"] for pkg in data["rows"]]
        print(f"Successfully fetched {len(all_packages)} top packages")
        save_top_packages_cache(all_packages)
        return all_packages[:limit]
    except Exception as e:
        print(f"Failed to fetch top packages: {e}")
        return []


async def get_packages(url) -> list[str]:
    """Fetch packages from a PyPI URL, using Playwright if needed for Fastly bypass."""
    # Check cache first
    cached = get_packages_cache(url)
    if cached:
        print(f"Using cached packages from {url}")
        return cached

    print(f"Fetching packages from {url}...")

    # First try with httpx
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    response = None
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, follow_redirects=True, timeout=10)
        print(f"  Status: {response.status_code}")
    except httpx.RequestError as e:
        print(f"  Request failed: {e}")

    # Check if we got useful content
    should_use_playwright = False

    if response and response.status_code == 200:
        if "A required part of this site couldn't load" in response.text:
            should_use_playwright = True
            print("  Fastly JS challenge detected")
        else:
            # Parse the HTML content
            soup = BeautifulSoup(response.content, "html.parser")
            # Filter h3 tags to package names (not all-uppercase headers or archived)
            h3_tags = []
            for h3 in soup.find_all("h3"):
                text = h3.get_text(strip=True)
                if (
                    text
                    and len(text) > 0
                    and not text.isupper()
                    and "Archived" not in text
                    and "archived" not in text
                ):
                    h3_tags.append(text)
            h3_tags.sort()

            if h3_tags:
                print(f"  Successfully fetched {len(h3_tags)} packages with httpx")
                save_packages_cache(url, h3_tags)
                return h3_tags
            else:
                print(f"  Request succeeded but no h3 tags found, trying Playwright")
                should_use_playwright = True
    else:
        status = response.status_code if response else "No response"
        print(f"  Request failed with status: {status}, trying Playwright")
        should_use_playwright = True

    # Try Playwright if httpx didn't work
    if should_use_playwright:
        print(f"  Trying Playwright...")
        try:
            h3_tags = await get_packages_with_playwright(url)
            if h3_tags:
                print(f"  Successfully fetched {len(h3_tags)} packages using Playwright")
                save_packages_cache(url, h3_tags)
                return h3_tags
            else:
                print(f"  Playwright returned no h3 tags")
        except Exception as e:
            print(f"  Playwright failed: {e}")

    # If Playwright is not available or failed, fall back to manual input
    print(
        "Could not fetch automatically. You can try `Array.from(document.querySelectorAll('h3')).map(h3 => h3.innerText).join('\\n');` in your browser's JS console and paste the results below:"
    )
    print("Paste package names (one per line, empty line to finish):")
    packages = []
    while res := input():
        if not res:
            break
        packages.append(res.split(" ")[0])

    if packages:
        print(f"Received {len(packages)} packages")
        save_packages_cache(url, packages)
        return packages

    print("No packages provided")
    exit(1)


async def get_last_release_time(
    client: httpx.AsyncClient, package_name: str
) -> tuple[float, str]:
    """Get timestamp and human-readable time since last release for a package.

    Returns: (timestamp_seconds, human_readable_string)
    """
    # Check release time cache first
    cached = get_cached_release_time(package_name)
    if cached is not None:
        return cached

    # Check PyPI response cache
    data = get_cached_pypi_response(package_name)

    try:
        if data is None:
            # Fetch from PyPI if not cached
            response = await client.get(
                f"https://pypi.org/pypi/{package_name}/json", timeout=5
            )
            if response.status_code == 404:
                # Package doesn't exist on PyPI - don't cache
                return (float("inf"), "not found")
            response.raise_for_status()
            data = response.json()
            # Cache the PyPI response
            save_pypi_response_cache(package_name, data)

        releases = data["releases"]
        if not releases:
            # No releases - don't cache
            return (float("inf"), "unknown")
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
                # No upload time found - don't cache
                return (float("inf"), "unknown")
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
                # Only cache successful results
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


def get_repo_url(package_name: str) -> str:
    """Extract repository URL from cached PyPI data."""
    data = get_cached_pypi_response(package_name)
    if not data:
        return ""
    project_urls = data.get("info", {}).get("project_urls") or {}
    # Normalize keys to lowercase for matching
    urls_lower = {k.lower(): v for k, v in project_urls.items()}
    for key in ("source", "source code", "repository", "github", "code", "homepage"):
        url = urls_lower.get(key, "")
        if "github.com" in url or "gitlab.com" in url or "codeberg.org" in url or "bitbucket.org" in url:
            return url
    # Fallback: any project_url pointing to a known forge
    for url in project_urls.values():
        if url and ("github.com" in url or "gitlab.com" in url or "codeberg.org" in url or "bitbucket.org" in url):
            return url
    # Fallback: check home_page
    homepage = data.get("info", {}).get("home_page", "") or ""
    if "github.com" in homepage or "gitlab.com" in homepage:
        return homepage
    return ""


async def get_tidelift_data(packages, only_liftable=False):
    """Fetch tidelift data and return enriched package information."""
    # Check cache first
    cached = get_tidelift_cache(packages)
    if cached:
        print(f"[CACHE HIT] Tidelift data for {len(packages)} packages")
        # Ensure PyPI data is fetched for repo_url backfill
        names_needing_pypi = [item["name"] for item in cached if not item.get("repo_url")]
        if names_needing_pypi:
            await fetch_release_times(names_needing_pypi)
            for item in cached:
                if not item.get("repo_url"):
                    item["repo_url"] = get_repo_url(item["name"])
        return cached

    print(f"[API REQUEST] Fetching Tidelift data for {len(packages)} packages...")

    # Batch requests to avoid API limits
    BATCH_SIZE = 500
    response_data = []
    async with httpx.AsyncClient() as client:
        for i in range(0, len(packages), BATCH_SIZE):
            batch = packages[i:i + BATCH_SIZE]
            packages_data = [{"platform": "pypi", "name": h3} for h3 in batch]
            data = {"packages": packages_data}
            res = await client.post(
                "https://tidelift.com/api/depci/estimate/bulk_estimates", json=data,
                timeout=30,
            )
            res.raise_for_status()
            response_data.extend(res.json())
            if i + BATCH_SIZE < len(packages):
                print(f"  Fetched {min(i + BATCH_SIZE, len(packages))}/{len(packages)}...")

    # Collecting all package data
    package_data = []

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
    print(f"[API REQUEST] Fetching PyPI release info for {len(packages_to_fetch)} packages...")
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
                "repo_url": get_repo_url(name),
            }
        )

    # Save to cache
    save_tidelift_cache(packages, result)
    return result


def print_csv(data: list[dict]) -> None:
    """Print package data as CSV to stdout."""
    import csv as csv_mod
    import io

    output = io.StringIO()
    writer = csv_mod.writer(output, lineterminator="\n")
    writer.writerow(["name", "url", "estimated_money", "lifted", "last_release", "repo_url"])
    for item in data:
        ts = item.get("last_release_timestamp")
        if ts and ts != float("inf"):
            release = datetime.fromtimestamp(ts).date().isoformat()
        else:
            release = ""
        writer.writerow([
            item["name"],
            f"https://pypi.org/project/{item['name']}",
            item.get("estimated_money", ""),
            item.get("lifted", ""),
            release,
            item.get("repo_url", ""),
        ])
    sys.stdout.write(output.getvalue())


def print_table(data: list[dict]) -> None:
    """Print package data as a rich table."""
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#")
    table.add_column("Package Name")
    table.add_column("Url")
    table.add_column("Estimated Money")
    table.add_column("Lifted")
    table.add_column("Last Release")
    table.add_column("Repo")

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
        release_timestamp = item.get("last_release_timestamp", float("inf"))
        release_style = get_release_style(release_timestamp)
        table.add_row(
            str(i),
            item["name"],
            f"https://pypi.org/project/{item['name']}",
            money_str,
            f"[green]{lifted_str}[/green]" if lifted_str == "✓" else f"[red]{lifted_str}[/red]",
            f"[{release_style}]{item['last_release']}[/{release_style}]",
            item.get("repo_url", ""),
        )

    print(table)


class TideApp(App):
    """Textual app for viewing Tidelift package data."""

    CSS = """
    .hidden {
        display: none;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("s", "sort_lifted", "Sort by Lifted"),
        Binding("m", "sort_money", "Sort by Money"),
        Binding("n", "sort_name", "Sort by Name"),
        Binding("l", "sort_release", "Sort by Release"),
        Binding("r", "sort_repo", "Sort by Repo"),
        Binding("/", "focus_search", "Search"),
        Binding("escape", "clear_search", "Clear Search"),
    ]

    def __init__(self, data: list[dict]):
        super().__init__()
        self.data = data
        self.sort_column = None
        self.sort_reverse = False
        self.filter_text = ""

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Header()
        yield Input(placeholder="Filter packages...", id="search", classes="hidden")
        yield DataTable(id="packages-table")
        yield Footer()

    def on_mount(self) -> None:
        """Setup app when it starts."""
        table = self.query_one(DataTable)
        # Add columns once
        table.add_column("Package Name", key="name")
        table.add_column("Lifted", key="lifted")
        table.add_column("Estimated Money", key="estimated_money")
        table.add_column("Last Release", key="last_release")
        table.add_column("Repo", key="repo_url")
        self.populate_table()

    def populate_table(self) -> None:
        """Populate the data table."""
        table = self.query_one(DataTable)
        # Clear only rows, not columns
        table.clear(columns=False)

        # Sort data
        sorted_data = self.get_sorted_data()

        # Add rows with styling
        for item in sorted_data:
            # Determine lifted status styling
            if item["lifted"] is True:
                lifted_style = "bold green"
                lifted_str = "✓"
            elif item["lifted"] is False:
                lifted_style = "bold yellow"
                lifted_str = "✗"
            else:
                lifted_style = "dim"
                lifted_str = "—"

            # Determine money styling
            money_str = (
                str(item["estimated_money"])
                if item["estimated_money"] is not None
                else "--"
            )
            money_style = "cyan" if item["estimated_money"] is not None else "dim"

            # Determine release time styling based on timestamp
            release_str = item["last_release"]
            release_timestamp = item.get("last_release_timestamp", float("inf"))
            release_style = get_release_style(release_timestamp)

            table.add_row(
                item["name"],
                Text(lifted_str, style=lifted_style),
                Text(money_str, style=money_style),
                Text(release_str, style=release_style),
                item.get("repo_url", ""),
            )

    def get_filtered_data(self) -> list[dict]:
        """Filter data based on search text."""
        if not self.filter_text:
            return self.data
        q = self.filter_text.lower()
        return [
            item for item in self.data
            if q in item["name"].lower()
            or q in item.get("repo_url", "").lower()
        ]

    def get_sorted_data(self) -> list[dict]:
        """Get filtered and sorted package data."""
        data = self.get_filtered_data()

        def maybefloat(x):
            if x is None:
                return 0
            try:
                return float(x)
            except (TypeError, ValueError):
                return 0

        if self.sort_column == "lifted":
            sorted_data = sorted(
                data,
                key=lambda x: (
                    x["lifted"] is None,
                    x["lifted"] is False,
                    x["name"],
                ),
                reverse=self.sort_reverse,
            )
        elif self.sort_column == "money":
            sorted_data = sorted(
                data,
                key=lambda x: (maybefloat(x["estimated_money"]), x["name"]),
                reverse=not self.sort_reverse,
            )
        elif self.sort_column == "release":
            sorted_data = sorted(
                data,
                key=lambda x: (x["last_release_timestamp"], x["name"]),
                reverse=not self.sort_reverse,
            )
        elif self.sort_column == "repo":
            sorted_data = sorted(
                data,
                key=lambda x: (x.get("repo_url", ""), x["name"]),
                reverse=self.sort_reverse,
            )
        else:
            # Default sort: by lifted, then money, then name
            sorted_data = sorted(
                data,
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

    def action_sort_repo(self) -> None:
        """Sort by repo URL."""
        if self.sort_column == "repo":
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = "repo"
            self.sort_reverse = False
        self.populate_table()

    def action_focus_search(self) -> None:
        """Show and focus the search input."""
        search = self.query_one("#search", Input)
        search.remove_class("hidden")
        search.value = ""
        self.call_later(search.focus)

    def action_clear_search(self) -> None:
        """Clear search, hide input, and refocus table."""
        search = self.query_one("#search", Input)
        search.value = ""
        search.add_class("hidden")
        self.filter_text = ""
        self.populate_table()
        self.query_one(DataTable).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter table when search input changes."""
        self.filter_text = event.value
        self.populate_table()


def get_release_style(timestamp: float) -> str:
    """Determine color style based on release timestamp duration.

    Returns style string based on how old the release is:
    - < 1 month: blue
    - 1 month - 6 months: green
    - 6 months - 2 years: yellow
    - > 2 years: red
    - unknown/not found: red
    """
    if timestamp == float("inf"):
        return "red"

    release_dt = datetime.fromtimestamp(timestamp)
    now = datetime.now(release_dt.tzinfo) if release_dt.tzinfo else datetime.now()
    delta = now - release_dt
    days = delta.days

    if days < 30:
        return "blue"
    elif days < 180:  # 6 months
        return "green"
    elif days < 730:  # 2 years
        return "yellow"
    else:  # 2+ years
        return "red"


def clear_cache():
    """Clear all cached data."""
    import shutil
    if CACHE_DIR.exists():
        shutil.rmtree(CACHE_DIR)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Cache cleared: {CACHE_DIR}")
    else:
        print("Cache directory does not exist")


app_cli = typer.Typer(help="Analyze Tidelift lifted packages and their release status")


async def fetch_all_data(
    org: Optional[str],
    user: Optional[str],
    packages: Optional[List[str]],
    top: Optional[int],
    only_liftable: bool,
):
    """Async function to fetch all data."""
    package_list = []

    if org:
        url = f"https://pypi.org/org/{org}/"
        package_list += await get_packages(url)

    if user:
        url = f"https://pypi.org/user/{user}/"
        package_list += await get_packages(url)

    if packages:
        package_list += packages

    if top is not None:
        limit = top if top > 0 else 500
        package_list += await get_top_packages(limit)

    if not package_list:
        typer.echo("Error: No packages specified. Use --org, --user, --packages, or --top")
        raise typer.Exit(1)

    # Fetch data
    data = await get_tidelift_data(package_list, only_liftable=only_liftable)
    return data


@app_cli.command()
def main(
    org: Optional[str] = typer.Option(None, "--org", help="PyPI organization name"),
    user: Optional[str] = typer.Option(None, "--user", help="PyPI user name"),
    packages: Optional[List[str]] = typer.Argument(None, help="Package names"),
    top: Optional[int] = typer.Option(None, "--top", help="Fetch top N most downloaded packages (default 500)"),
    only_liftable: bool = typer.Option(False, "--only-liftable", help="Show only liftable packages"),
    trim_lifted: bool = typer.Option(False, "--trim-lifted", help="Exclude already lifted packages"),
    app: bool = typer.Option(False, "--app", help="Launch interactive TUI"),
    csv: bool = typer.Option(False, "--csv", help="Output as CSV"),
    clear_cache_flag: bool = typer.Option(False, "--clear-cache", help="Clear all cached data and exit"),
):
    """Analyze Tidelift package lift status and release dates."""
    if clear_cache_flag:
        clear_cache()
        raise typer.Exit(0)

    # Fetch all data in an async context
    data = asyncio.run(fetch_all_data(org, user, packages, top, only_liftable))

    if trim_lifted:
        data = [item for item in data if item.get("lifted") is not True]

    # Launch app or print table (both are blocking/sync)
    if csv:
        print_csv(data)
    elif app:
        tui_app = TideApp(data)
        tui_app.run()
    else:
        print_table(data)


if __name__ == "__main__":
    app_cli()
