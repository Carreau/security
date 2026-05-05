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
from datetime import datetime
import json
import httpx
import asyncio
from pathlib import Path
from textual.app import ComposeResult, App
from textual.widgets import DataTable, Footer, Header, Input
from textual.binding import Binding
from rich.text import Text
import typer
from typing import Optional, List


CACHE_DIR = Path.home() / ".cache" / "tide"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_SECONDS = 3600  # 1 hour


def get_cache_file(package_name: str, type: str = "release") -> Path:
    return CACHE_DIR / f"{package_name}_{type}.json"


def get_cached_release_time(package_name: str) -> tuple[float, str] | None:
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
    cache_file = CACHE_DIR / "top_packages.json"
    with open(cache_file, "w") as f:
        json.dump(
            {
                "cache_timestamp": datetime.now().timestamp(),
                "packages": packages,
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
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_extra_http_headers(
                {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                }
            )
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_timeout(1000)
            content = await page.content()
            await browser.close()

            soup = BeautifulSoup(content, "html.parser")
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

            return h3_tags if h3_tags else None
    except Exception as e:
        error_str = str(e).lower()
        if "executable" in error_str or "browser" in error_str or "not found" in error_str:
            print(
                "\n  Playwright browser binaries not found. Installing..."
            )
            import subprocess
            try:
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=True,
                    timeout=120,
                )
                print("  Chromium installed. Retrying fetch...")
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
    cached = get_top_packages_cache(limit)
    if cached:
        print(f"Using cached top {limit} packages")
        return cached

    print(f"Fetching top {limit} most downloaded PyPI packages...")
    try:
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
    cached = get_packages_cache(url)
    if cached:
        print(f"Using cached packages from {url}")
        return cached

    print(f"Fetching packages from {url}...")

    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    response = None
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, follow_redirects=True, timeout=10)
        print(f"  Status: {response.status_code}")
    except httpx.RequestError as e:
        print(f"  Request failed: {e}")

    should_use_playwright = False

    if response and response.status_code == 200:
        if "A required part of this site couldn't load" in response.text:
            should_use_playwright = True
            print("  Fastly JS challenge detected")
        else:
            soup = BeautifulSoup(response.content, "html.parser")
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


def get_cached_trusted_publisher(package_name: str) -> bool | None:
    cache_file = CACHE_DIR / f"{package_name}_tp.json"
    if not cache_file.exists():
        return None
    try:
        with open(cache_file) as f:
            data = json.load(f)
        cache_timestamp = data.get("cache_timestamp", 0)
        if datetime.now().timestamp() - cache_timestamp < CACHE_TTL_SECONDS:
            return data.get("trusted_publisher")
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


def save_trusted_publisher_cache(package_name: str, trusted_publisher: bool):
    cache_file = CACHE_DIR / f"{package_name}_tp.json"
    with open(cache_file, "w") as f:
        json.dump(
            {
                "cache_timestamp": datetime.now().timestamp(),
                "trusted_publisher": trusted_publisher,
            },
            f,
        )


FASTLY_BLOCKED = "fastly_blocked"


async def fetch_project_page_with_playwright(package_name: str) -> str | None:
    """Render a PyPI project page in headless Chromium to bypass Fastly."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    url = f"https://pypi.org/project/{package_name}/"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_extra_http_headers(
                {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                }
            )
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_timeout(1000)
            content = await page.content()
            await browser.close()
            return content
    except Exception as e:
        error_str = str(e).lower()
        if "executable" in error_str or "browser" in error_str or "not found" in error_str:
            print("\n  Playwright browser binaries not found. Installing...")
            import subprocess
            try:
                subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    check=True,
                    timeout=300,
                )
                print("  Chromium installed. Retrying fetch...")
                return await fetch_project_page_with_playwright(package_name)
            except Exception as install_error:
                print(f"\n  Failed to auto-install browsers: {install_error}")
                print("  Try manually installing with:")
                print("    uv run playwright install chromium\n")
        else:
            print(f"  Playwright error for {package_name}: {e}")
        return None


def _parse_trusted_publisher(html: str) -> bool | str | None:
    """Parse a project-page HTML body.

    Returns True/False if a sidebar was found, FASTLY_BLOCKED on the JS
    challenge, or None if the page didn't look like a project page.
    """
    if "Client Challenge" in html and "sidebar-section" not in html:
        return FASTLY_BLOCKED

    soup = BeautifulSoup(html, "html.parser")
    if not soup.select("div.sidebar-section"):
        return None

    for verified in soup.select("div.sidebar-section.verified"):
        for h6 in verified.find_all("h6"):
            if "GitHub Statistics" in h6.get_text():
                return True
    return False


async def check_trusted_publisher(
    client: httpx.AsyncClient, package_name: str
) -> bool | str | None:
    """Check whether a package uses Trusted Publishing.

    Looks for a "GitHub Statistics" subsection inside the sidebar's
    `div.sidebar-section.verified` block. The verified block alone is too broad
    (it also fires for PyPI-org-owned packages whose Owner is verified, e.g.
    django, numpy); GitHub Statistics specifically indicates the project's
    source URL was verified — which only happens through Trusted Publishing.

    Returns True/False on detection, FASTLY_BLOCKED if Fastly served the bot
    challenge and Playwright also failed, or None for other undetectable cases
    (404, network error). The blocked sentinel is not cached so subsequent
    runs retry.
    """
    cached = get_cached_trusted_publisher(package_name)
    if cached is not None:
        return cached

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
    }
    try:
        resp = await client.get(
            f"https://pypi.org/project/{package_name}/",
            headers=headers,
            timeout=10,
            follow_redirects=True,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
    except httpx.RequestError:
        return None

    result = _parse_trusted_publisher(resp.text)

    if result == FASTLY_BLOCKED:
        # Fall back to a real browser to solve the JS challenge.
        print(f"  Fastly challenge for {package_name}, retrying with Playwright")
        rendered = await fetch_project_page_with_playwright(package_name)
        if rendered is not None:
            result = _parse_trusted_publisher(rendered)

    if result is True or result is False:
        save_trusted_publisher_cache(package_name, result)
    return result


async def get_last_release_time(
    client: httpx.AsyncClient, package_name: str
) -> tuple[float, str]:
    """Get timestamp and human-readable time since last release for a package."""
    cached = get_cached_release_time(package_name)
    if cached is not None:
        return cached

    data = get_cached_pypi_response(package_name)

    try:
        if data is None:
            response = await client.get(
                f"https://pypi.org/pypi/{package_name}/json", timeout=5
            )
            if response.status_code == 404:
                return (float("inf"), "not found")
            response.raise_for_status()
            data = response.json()
            save_pypi_response_cache(package_name, data)

        releases = data["releases"]
        if not releases:
            return (float("inf"), "unknown")

        latest_upload_time = None
        for version, files in releases.items():
            if not files:
                continue
            upload_time = files[0]["upload_time_iso_8601"]
            if latest_upload_time is None or upload_time > latest_upload_time:
                latest_upload_time = upload_time

        if not latest_upload_time:
            return (float("inf"), "unknown")

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

            parts = [f"{years}y"]
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
    release_times = {}

    async with httpx.AsyncClient() as client:

        async def fetch_with_client(name):
            release_times[name] = await get_last_release_time(client, name)

        tasks = [fetch_with_client(name) for name in packages]
        await asyncio.gather(*tasks)

    return release_times


async def fetch_trusted_publisher(
    packages: list[str],
) -> dict[str, bool | str | None]:
    results: dict[str, bool | str | None] = {}

    async with httpx.AsyncClient() as client:

        async def fetch_with_client(name):
            results[name] = await check_trusted_publisher(client, name)

        tasks = [fetch_with_client(name) for name in packages]
        await asyncio.gather(*tasks)

    return results


def get_repo_url(package_name: str) -> str:
    """Extract repository URL from cached PyPI data."""
    data = get_cached_pypi_response(package_name)
    if not data:
        return ""
    project_urls = data.get("info", {}).get("project_urls") or {}
    urls_lower = {k.lower(): v for k, v in project_urls.items()}
    for key in ("source", "source code", "repository", "github", "code", "homepage"):
        url = urls_lower.get(key, "")
        if "github.com" in url or "gitlab.com" in url or "codeberg.org" in url or "bitbucket.org" in url:
            return url
    for url in project_urls.values():
        if url and ("github.com" in url or "gitlab.com" in url or "codeberg.org" in url or "bitbucket.org" in url):
            return url
    homepage = data.get("info", {}).get("home_page", "") or ""
    if "github.com" in homepage or "gitlab.com" in homepage:
        return homepage
    return ""


async def collect_package_data(packages: list[str]) -> list[dict]:
    """Fetch release times, repo URLs and trusted-publisher status for packages."""
    print(f"[API REQUEST] Fetching PyPI release info for {len(packages)} packages...")
    release_times = await fetch_release_times(packages)

    print(f"[API REQUEST] Checking trusted-publisher status for {len(packages)} packages...")
    trusted_publisher = await fetch_trusted_publisher(packages)

    result = []
    for name in packages:
        release_timestamp, release_display = release_times.get(
            name, (float("inf"), "unknown")
        )
        result.append(
            {
                "name": name,
                "last_release": release_display,
                "last_release_timestamp": release_timestamp,
                "repo_url": get_repo_url(name),
                "trusted_publisher": trusted_publisher.get(name),
            }
        )
    return result


def print_csv(data: list[dict]) -> None:
    """Print package data as CSV to stdout."""
    import csv as csv_mod
    import io

    output = io.StringIO()
    writer = csv_mod.writer(output, lineterminator="\n")
    writer.writerow([
        "name",
        "url",
        "last_release",
        "repo_url",
        "trusted_publisher",
    ])
    for item in data:
        ts = item.get("last_release_timestamp")
        if ts and ts != float("inf"):
            release = datetime.fromtimestamp(ts).date().isoformat()
        else:
            release = ""
        tp = item.get("trusted_publisher")
        if tp is True or tp is False:
            tp_str = str(tp).lower()
        elif tp == FASTLY_BLOCKED:
            tp_str = "fastly_blocked"
        else:
            tp_str = ""
        writer.writerow([
            item["name"],
            f"https://pypi.org/project/{item['name']}",
            release,
            item.get("repo_url", ""),
            tp_str,
        ])
    sys.stdout.write(output.getvalue())


def print_table(data: list[dict]) -> None:
    """Print package data as a rich table."""
    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("#")
    table.add_column("Package Name")
    table.add_column("Url")
    table.add_column("Last Release")
    table.add_column("Repo")
    table.add_column("Trusted Publisher")

    sorted_data = sorted(
        data,
        key=lambda x: (
            x.get("trusted_publisher") is not True,
            x["last_release_timestamp"],
            x["name"],
        ),
    )

    for i, item in enumerate(sorted_data, start=1):
        release_timestamp = item.get("last_release_timestamp", float("inf"))
        release_style = get_release_style(release_timestamp)
        tp = item.get("trusted_publisher")
        if tp is True:
            tp_cell = "[green]✓[/green]"
        elif tp is False:
            tp_cell = "[red]✗[/red]"
        elif tp == FASTLY_BLOCKED:
            tp_cell = "[yellow](fastly blocked)[/yellow]"
        else:
            tp_cell = "[dim]-[/dim]"
        table.add_row(
            str(i),
            item["name"],
            f"https://pypi.org/project/{item['name']}",
            f"[{release_style}]{item['last_release']}[/{release_style}]",
            item.get("repo_url", ""),
            tp_cell,
        )

    print(table)


class TideApp(App):
    """Textual app for viewing PyPI package data."""

    CSS = """
    .hidden {
        display: none;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("n", "sort_name", "Sort by Name"),
        Binding("l", "sort_release", "Sort by Release"),
        Binding("r", "sort_repo", "Sort by Repo"),
        Binding("t", "sort_tp", "Sort by Trusted Publisher"),
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
        yield Header()
        yield Input(placeholder="Filter packages...", id="search", classes="hidden")
        yield DataTable(id="packages-table")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_column("Package Name", key="name")
        table.add_column("Last Release", key="last_release")
        table.add_column("Repo", key="repo_url")
        table.add_column("Trusted Publisher", key="trusted_publisher")
        self.populate_table()
        # The Input is composed first; explicitly focus the table so the
        # hidden search field doesn't grab focus on startup.
        table.focus()

    def populate_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=False)

        sorted_data = self.get_sorted_data()

        for item in sorted_data:
            release_str = item["last_release"]
            release_timestamp = item.get("last_release_timestamp", float("inf"))
            release_style = get_release_style(release_timestamp)

            tp = item.get("trusted_publisher")
            if tp is True:
                tp_text = Text("✓", style="bold green")
            elif tp is False:
                tp_text = Text("✗", style="bold yellow")
            elif tp == FASTLY_BLOCKED:
                tp_text = Text("(fastly blocked)", style="yellow")
            else:
                tp_text = Text("—", style="dim")

            table.add_row(
                item["name"],
                Text(release_str, style=release_style),
                item.get("repo_url", ""),
                tp_text,
            )

    def get_filtered_data(self) -> list[dict]:
        if not self.filter_text:
            return self.data
        q = self.filter_text.lower()
        return [
            item for item in self.data
            if q in item["name"].lower()
            or q in item.get("repo_url", "").lower()
        ]

    def get_sorted_data(self) -> list[dict]:
        data = self.get_filtered_data()

        if self.sort_column == "release":
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
        elif self.sort_column == "tp":
            sorted_data = sorted(
                data,
                key=lambda x: (
                    x.get("trusted_publisher") is not True,
                    x.get("trusted_publisher") is None,
                    x["name"],
                ),
                reverse=self.sort_reverse,
            )
        elif self.sort_column == "name":
            sorted_data = sorted(
                data, key=lambda x: x["name"], reverse=self.sort_reverse
            )
        else:
            sorted_data = sorted(
                data,
                key=lambda x: (
                    x.get("trusted_publisher") is not True,
                    x["last_release_timestamp"],
                    x["name"],
                ),
            )

        return sorted_data

    def action_sort_name(self) -> None:
        if self.sort_column == "name":
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = "name"
            self.sort_reverse = False
        self.populate_table()

    def action_sort_release(self) -> None:
        if self.sort_column == "release":
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = "release"
            self.sort_reverse = False
        self.populate_table()

    def action_sort_repo(self) -> None:
        if self.sort_column == "repo":
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = "repo"
            self.sort_reverse = False
        self.populate_table()

    def action_sort_tp(self) -> None:
        if self.sort_column == "tp":
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = "tp"
            self.sort_reverse = False
        self.populate_table()

    def action_focus_search(self) -> None:
        search = self.query_one("#search", Input)
        search.remove_class("hidden")
        search.value = ""
        self.call_later(search.focus)

    def action_clear_search(self) -> None:
        search = self.query_one("#search", Input)
        search.value = ""
        search.add_class("hidden")
        self.filter_text = ""
        self.populate_table()
        self.query_one(DataTable).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        self.filter_text = event.value
        self.populate_table()


def get_release_style(timestamp: float) -> str:
    """Determine color style based on release timestamp duration."""
    if timestamp == float("inf"):
        return "red"

    release_dt = datetime.fromtimestamp(timestamp)
    now = datetime.now(release_dt.tzinfo) if release_dt.tzinfo else datetime.now()
    delta = now - release_dt
    days = delta.days

    if days < 30:
        return "blue"
    elif days < 180:
        return "green"
    elif days < 730:
        return "yellow"
    else:
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


app_cli = typer.Typer(help="Inspect PyPI packages: release date, repo URL, Trusted Publishing")


async def fetch_all_data(
    org: Optional[str],
    user: Optional[str],
    packages: Optional[List[str]],
    top: Optional[int],
):
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

    return await collect_package_data(package_list)


@app_cli.command()
def main(
    org: Optional[str] = typer.Option(None, "--org", help="PyPI organization name"),
    user: Optional[str] = typer.Option(None, "--user", help="PyPI user name"),
    packages: Optional[List[str]] = typer.Argument(None, help="Package names"),
    top: Optional[int] = typer.Option(None, "--top", help="Fetch top N most downloaded packages (default 500)"),
    app: bool = typer.Option(False, "--app", help="Launch interactive TUI"),
    csv: bool = typer.Option(False, "--csv", help="Output as CSV"),
    clear_cache_flag: bool = typer.Option(False, "--clear-cache", help="Clear all cached data and exit"),
):
    """Inspect PyPI packages: release date, repo URL, Trusted Publishing."""
    if clear_cache_flag:
        clear_cache()
        raise typer.Exit(0)

    data = asyncio.run(fetch_all_data(org, user, packages, top))

    if csv:
        print_csv(data)
    elif app:
        tui_app = TideApp(data)
        tui_app.run()
    else:
        print_table(data)


if __name__ == "__main__":
    app_cli()
