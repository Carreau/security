
import asyncio
import json
from pathlib import Path
from datetime import datetime
import httpx
from bs4 import BeautifulSoup
import sys
from playwright.async_api import async_playwright

# --- Cache Management (adapted from tools/tide.py) ---

CACHE_DIR = Path.home() / ".cache" / "pypi_crawler"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_SECONDS = 3600 * 24  # 24 hours

def get_cache_file(key: str) -> Path:
    """Get the cache file path for a given key."""
    return CACHE_DIR / f"{key}.json"

def get_cached_data(key: str) -> dict | list | None:
    """Get cached data if it exists and is not expired."""
    cache_file = get_cache_file(key)
    if not cache_file.exists():
        return None

    try:
        with open(cache_file) as f:
            data = json.load(f)
        cache_timestamp = data.get("cache_timestamp", 0)
        if datetime.now().timestamp() - cache_timestamp < CACHE_TTL_SECONDS:
            return data.get("data")
    except (json.JSONDecodeError, KeyError, TypeError):
        pass
    return None

def save_cache(key: str, data_to_cache: dict | list):
    """Save data to cache."""
    cache_file = get_cache_file(key)
    with open(cache_file, "w") as f:
        json.dump(
            {
                "cache_timestamp": datetime.now().timestamp(),
                "data": data_to_cache,
            },
            f,
        )

# --- PyPI Scraping and API Calls ---

async def get_packages_with_playwright(url: str) -> list[str] | None:
    """Try to fetch packages using Playwright (handles JavaScript)."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle")
            content = await page.content()
            await browser.close()

            soup = BeautifulSoup(content, "html.parser")
            package_links = soup.select('a[class*="package-snippet"]')
            packages = [link.find('h3', class_='package-snippet__title').get_text(strip=True) for link in package_links]
            return packages
    except Exception as e:
        if "playwright install" in str(e):
            print("Playwright browsers not installed. Please run 'playwright install'")
        else:
            print(f"Playwright error: {e}")
        return None


async def get_packages_for_entity(entity_name: str, entity_type: str) -> list[str]:
    """Fetch all packages for a given user or organization."""
    if entity_type not in ["user", "org"]:
        raise ValueError("entity_type must be 'user' or 'org'")

    url = f"https://pypi.org/{entity_type}/{entity_name}/"
    cache_key = f"packages_{entity_type}_{entity_name}"

    cached_packages = get_cached_data(cache_key)
    if cached_packages:
        print(f"Cache hit for packages of {entity_type} '{entity_name}'")
        return cached_packages

    print(f"Fetching packages for {entity_type} '{entity_name}' from {url}")
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"}
    packages = []
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, follow_redirects=True, timeout=15)
        
        if "Client Challenge" not in response.text:
            soup = BeautifulSoup(response.content, "html.parser")
            package_links = soup.select('a[class*="package-snippet"]')
            packages = [link.find('h3', class_='package-snippet__title').get_text(strip=True) for link in package_links]
    except httpx.RequestError as e:
        print(f"Error fetching {url}: {e}")

    if not packages:
        print("Falling back to Playwright to fetch packages.")
        packages = await get_packages_with_playwright(url)
        if packages is None:
            packages = []

    if packages:
        print(f"Found {len(packages)} packages for {entity_type} '{entity_name}'")
        save_cache(cache_key, packages)
    else:
        print(f"No packages found for {entity_type} '{entity_name}'")

    return packages


async def _get_maintainers_from_html(html_content: str) -> list[dict]:
    """Helper function to parse maintainers from HTML content."""
    soup = BeautifulSoup(html_content, 'html.parser')
    maintainers = []
    maintainers_heading = soup.find('h6', string='Maintainers')
    if maintainers_heading:
        sidebar_section = maintainers_heading.find_parent('div', class_='sidebar-section')
        if sidebar_section:
            maintainer_links = sidebar_section.select('a[href*="/user/"], a[href*="/org/"]')
            for link in maintainer_links:
                href = link.get('href')
                name_span = link.find('span', class_='sidebar-section__user-gravatar-text')
                if not name_span:
                    continue
                name = name_span.get_text(strip=True)
                if '/user/' in href:
                    maintainers.append({'name': name, 'type': 'user'})
                elif '/org/' in href:
                    maintainers.append({'name': name, 'type': 'org'})
    return [dict(t) for t in {tuple(d.items()) for d in maintainers}]

async def get_maintainers_for_package(package_name: str) -> tuple[list[dict], int, str]:
    """
    Fetch all maintainers (users and orgs) for a given package.
    Returns a tuple: (list of maintainers, count of maintainers, status_string)
    status_string can be 'fetched', 'not_found', 'error'
    """
    url = f"https://pypi.org/project/{package_name}/"
    cache_key = f"maintainers_{package_name}"

    cached_data = get_cached_data(cache_key)
    if cached_data:
        print(f"Cache hit for maintainers of '{package_name}'")
        return cached_data['maintainers'], cached_data['count'], cached_data['status']

    print(f"Fetching maintainers for '{package_name}' from {url}")
    
    maintainers = []
    status = 'error' # Default status
    maintainer_count = 0

    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=15)
            response.raise_for_status() # Raise for HTTP errors
        
        if response.status_code == 404:
            status = 'not_found'
        elif "Client Challenge" in response.text:
            # Fallback to Playwright if httpx is blocked
            print(f"Falling back to Playwright to fetch maintainers for '{package_name}'.")
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page()
                    await page.goto(url, wait_until="networkidle")
                    content = await page.content()
                    await browser.close()
                    maintainers = await _get_maintainers_from_html(content)
                    status = 'fetched'
            except Exception as e:
                if "playwright install" in str(e):
                    print("Playwright browsers not installed. Please run 'playwright install'")
                else:
                    print(f"Playwright error: {e}")
                status = 'error'
        else:
            maintainers = await _get_maintainers_from_html(response.text)
            status = 'fetched'
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            status = 'not_found'
        else:
            print(f"HTTP error fetching {url}: {e}")
            status = 'error'
    except httpx.RequestError as e:
        print(f"Request error fetching {url}: {e}")
        status = 'error'

    maintainer_count = len(maintainers)
    
    # Save cache regardless of status (even for not_found or error) to avoid re-fetching
    save_cache(cache_key, {'maintainers': maintainers, 'count': maintainer_count, 'status': status})

    if status == 'fetched':
        print(f"Found {maintainer_count} maintainers for '{package_name}'")
    else:
        print(f"Status for '{package_name}': {status} (Maintainer count: {maintainer_count})")

    return maintainers, maintainer_count, status
