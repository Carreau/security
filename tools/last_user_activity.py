"""
This tools find all users in multiple organizations and print their last activity date.
"""

import os
import asyncio
import aiohttp
from rich import print
from datetime import datetime
import humanize
from itertools import count

orgs = [
    "binder-examples",
    "binderhub-ci-repos", 
    "ipython",
    "jupyter",
    "jupyter-book",
    "jupyter-governance",
    "jupyter-incubator",
    "jupyter-server",
    "jupyter-standards",
    "jupyter-widgets",
    "jupyterhub",
    "jupyterlab",
    "jupyter-xeus",
    "jupytercon",
    "voila-dashboards",
    "voila-gallery",
]

token = os.getenv("GH_TOKEN")
if not token:
    print("[red]Error: GH_TOKEN environment variable not set[/red]")
    exit(1)

headers = {
    "Authorization": f"token {token}",
    "Accept": "application/vnd.github.v3+json",
}

async def get_org_members(session: aiohttp.ClientSession, org: str) -> list[dict]:
    """Get all members for an organization
    
    Parameters
    ----------
    session: aiohttp.ClientSession
        The aiohttp client session
    org: str
        The organization name
        
    Returns
    -------
    list[dict]: The list of members
    """
    members = []
    
    for page in count(1):
        url = f"https://api.github.com/orgs/{org}/members?page={page}&per_page=100"
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                print(f"[red]Error fetching members for {org}: {response.status}[/red]")
                break
                
            page_members = await response.json()
            if not page_members:
                break
                
            members.extend(page_members)
            
    return members

async def get_user_activity(session: aiohttp.ClientSession, username: str) -> datetime:
    """Get the last activity date for a user
    
    Parameters
    ----------
    session: aiohttp.ClientSession
        The aiohttp client session
    username: str
        The GitHub username
        
    Returns
    -------
    datetime: The last activity date
    """
    url = f"https://api.github.com/users/{username}/events/public"
    async with session.get(url, headers=headers) as response:
        if response.status == 200:
            events = await response.json()
            if events:
                return datetime.fromisoformat(events[0]["created_at"].replace('Z', '+00:00'))
    return None

async def main():
    async with aiohttp.ClientSession() as session:
        # Check rate limit
        async with session.get("https://api.github.com/rate_limit", headers=headers) as response:
            if response.status == 200:
                rate_data = await response.json()
                remaining = rate_data["resources"]["core"]["remaining"]
                reset_time = datetime.fromtimestamp(rate_data["resources"]["core"]["reset"])
                reset_in = humanize.naturaltime(reset_time)
                print(f"Rate limit remaining: {remaining}")
                print(f"Rate limit resets {reset_in}")
                if remaining < 100:
                    print(f"[yellow]Warning: Low rate limit ({remaining} remaining)[/yellow]")
                    if remaining < 10:
                        print("[red]Aborting due to very low rate limit[/red]")
                        return

        # Get all members from all orgs
        all_members = {}
        for org in orgs:
            members = await get_org_members(session, org)
            for member in members:
                if member["login"] not in all_members:
                    all_members[member["login"]] = []
                all_members[member["login"]].append(org)

        # Get activity for each user
        tasks = []
        for username in all_members:
            task = get_user_activity(session, username)
            tasks.append((username, task))

        results = await asyncio.gather(*(task for _, task in tasks))

        # Print results sorted by last activity
        user_activities = []
        for (username, _), last_activity in zip(tasks, results):
            if last_activity:
                user_activities.append((username, last_activity, all_members[username]))

        for username, last_activity, user_orgs in sorted(user_activities, key=lambda x: x[1], reverse=True):
            last_activity_ago = humanize.naturaltime(datetime.now(last_activity.tzinfo) - last_activity)
            orgs_str = ", ".join(user_orgs)
            print(f"{username:<20}: Last activity {last_activity_ago} in orgs: {orgs_str}")

if __name__ == "__main__":
    asyncio.run(main())
