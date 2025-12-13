
import httpx

async def fetch_package_page(package: str):
    url = f"https://pypi.org/project/{package}/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        print(response.text)

if __name__ == "__main__":
    import asyncio
    asyncio.run(fetch_package_page("record-type"))
