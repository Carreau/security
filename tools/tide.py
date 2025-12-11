# https://packaging.python.org/en/latest/specifications/inline-script-metadata/
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "requests",
#   "rich",
#   "beautifulsoup4",
#   "trio",
#   "anyio[trio]",
#   "httpx",
# ]
# ///
import requests
from rich import print
from bs4 import BeautifulSoup
import sys
from rich.table import Table
from rich.prompt import Prompt
from datetime import datetime
import json
import httpx
import trio


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


async def get_last_release_time(client: httpx.AsyncClient, package_name: str) -> str:
    """Get human-readable time since last release for a package."""
    try:
        response = await client.get(
            f"https://pypi.org/pypi/{package_name}/json", timeout=5
        )
        response.raise_for_status()
        data = response.json()

        releases = data["releases"]
        if not releases:
            return "unknown"

        # Find the most recent release by actual upload date, not version number
        latest_upload_time = None
        for version, files in releases.items():
            if not files:
                continue
            upload_time = files[0]["upload_time_iso_8601"]
            if latest_upload_time is None or upload_time > latest_upload_time:
                latest_upload_time = upload_time

        if not latest_upload_time:
            return "unknown"

        release_dt = datetime.fromisoformat(latest_upload_time.replace("Z", "+00:00"))
        now = datetime.now(release_dt.tzinfo)
        delta = now - release_dt

        days = delta.days
        if days == 0:
            return "today"
        elif days == 1:
            return "1 day ago"
        elif days < 30:
            return f"{days} days ago"
        elif days < 365:
            months = days // 30
            return f"{months}m ago"
        else:
            years = days // 365
            remaining_days = days % 365
            months = remaining_days // 30

            parts = []
            parts.append(f"{years}y")
            if months > 0:
                parts.append(f"{months}m")

            return ", ".join(parts) + " ago"
    except (httpx.RequestError, KeyError, IndexError, ValueError):
        return "unknown"


async def fetch_release_times(packages: list[str]) -> dict[str, str]:
    """Fetch release times for multiple packages concurrently."""
    release_times = {}

    async with httpx.AsyncClient() as client:

        async def fetch_with_client(name):
            release_times[name] = await get_last_release_time(client, name)

        async with trio.open_nursery() as nursery:
            for name in packages:
                nursery.start_soon(fetch_with_client, name)

    return release_times


async def get_tidelift_data(packages, only_liftable=False):
    packages_data = [{"platform": "pypi", "name": h3} for h3 in packages]

    data = {"packages": packages_data}
    res = requests.post(
        "https://tidelift.com/api/depci/estimate/bulk_estimates", json=data
    )

    res.raise_for_status()

    # Collecting all package data for aligned printing
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

    # Print the collected data in aligned columns

    # Create a table for aligned output
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

    package_data.sort(
        key=lambda x: (x[1] is None, x[1], -maybefloat(x[2]), x[0])
    )  # sort lifted True first, then None, then False, then amount,  then by name

    # Fetch release times for lifted and liftable packages concurrently
    packages_to_fetch = [
        name
        for name, lifted, estimated_money in package_data
        if lifted or (estimated_money is not None)
    ]
    release_times = await fetch_release_times(packages_to_fetch)

    for i, (name, lifted, estimated_money) in enumerate(package_data, start=1):
        if lifted:
            last_release = release_times.get(name, "unknown")
            table.add_row(
                str(i),
                name,
                f"https://pypi.org/project/{name}",
                "-- need login ––",
                f"[green]{lifted}[/green]",
                last_release,
            )
        else:
            if only_liftable and estimated_money is None:
                continue
            last_release = release_times.get(name, "unknown")
            table.add_row(
                str(i),
                name,
                f"https://pypi.org/project/{name}",
                str(estimated_money),
                f"[red]{lifted}[/red]",
                last_release,
            )

    print(table)


if __name__ == "__main__":
    # URL of the webpage
    args = sys.argv[1:]
    packages = []
    only_liftable = False
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
        else:
            print(
                "Invalid argument. Please use either --org ORG, --user USER or --packages PACKAGE1 PACKAGE2 ..."
            )
            exit(1)

    async def main():
        await get_tidelift_data(packages, only_liftable=only_liftable)

    trio.run(main)
