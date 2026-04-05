import asyncio
import aiohttp
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from urllib.robotparser import RobotFileParser
import pandas as pd
import os
import traceback

async def fetch(session: aiohttp.ClientSession, url: str, max_concurrent: int) -> str:
    semaphore = asyncio.Semaphore(max_concurrent)
    async with semaphore:
        try:
            async with session.get(url, timeout=10) as response:
                html = await response.text()
                return html
        except Exception as err:
            tb = traceback.extract_tb(err.__traceback__)
            line_number = tb[-1].lineno
            print(f"Exception: {err} at line {line_number}")
            return None

async def can_fetch(session: aiohttp.ClientSession, user_agent: str, url: str) -> bool:
    parsed_url = urlparse(url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
    robots_url = f"{base_url}/robots.txt"

    rp = RobotFileParser()
    rp.set_url(robots_url)

    try:
        async with session.get(robots_url) as response:
            if response.status == 200:
                content = await response.text()
                rp.parse(content.splitlines())
            elif response.status == 403:
                return False
            elif response.status == 404:
                return True
    except Exception as err:
        tb = traceback.extract_tb(err.__traceback__)
        line_number = tb[-1].lineno
        print(f"Error fetching robots.txt: {err} at line {line_number}")
        return False

    return rp.can_fetch(user_agent, url)

async def extract_links(html_content: str, current_url: str) -> set[str]:
    links = set()
    soup = BeautifulSoup(html_content, 'lxml')
    html_links = soup.find_all('a')

    for link in html_links:
        absolute = urljoin(current_url, link.get('href'))
        parsed = urlparse(absolute)

        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.fragment:
            absolute = absolute.split("#")[0]

        links.add(absolute)

    return links

async def get_website_title(html_content: str):
    soup = BeautifulSoup(html_content, "lxml")
    title: str = ""
    if soup.title is not None and soup.title.string is not None:
        title = soup.title.string.strip()
    else:
        og_title = soup.find('meta', property='og:title')
        if og_title is not None and og_title.get("content") is not None:
            title = og_title["content"].strip()
        else:
            h1 = soup.find("h1")
            if h1 is not None:
                title = h1.text.strip()

    return title

async def get_website_description(html_content: str):
    soup = BeautifulSoup(html_content, "lxml")
    description: str = ""
    meta_desc = soup.find('meta', attrs={'name': 'description'})

    if meta_desc is not None and meta_desc.get("content") is not None:
        description = meta_desc["content"].strip()
    else:
        og_description = soup.find('meta', property='og:description')
        if og_description is not None and og_description.get("content") is not None:
            description = og_description["content"].strip()
        else:
            description = intelligently_get_website_description(html_content)

    return description

def intelligently_get_website_description(html_content: str):
    max_length = 160
    soup = BeautifulSoup(html_content, "lxml")
    description: str = ""

    # Priority 1: First paragraph in main content
    main_content = soup.find('main') or soup.find("article") or soup.find("body")

    if main_content is not None:
        paragraphs = main_content.find_all('p')
        for p in paragraphs:
            text = p.get_text().strip()
            if len(text) > 50:
                description = text[:max_length] + "..."

    # Priority 2: First paragraph anywhere
    first_paragraph = soup.find('p')
    if first_paragraph is not None:
        text = first_paragraph.get_text().strip()
        if len(text) > 50:
            description = text[:max_length] + "..."

    # Priority 3: First 50 characters of visible text
    body_text = soup.get_text()
    visible_text = ' '.join(body_text.split())
    if visible_text is not None:
        if len(visible_text) > 50:
            description = visible_text[:max_length] + "..."

    return description

async def worker(queue: asyncio.Queue, visited: set, info_of_urls: dict, max_concurrent: int, headers: dict[str, str]):
    max_pages=50
    crawled_count = 0
    request_timeout = 10

    timeout = aiohttp.ClientTimeout(
            total=request_timeout,
            connect=request_timeout,
            sock_read=request_timeout
        )

    while queue and crawled_count < max_pages:
        try:
            url = await queue.get()

            if url in visited or crawled_count >= max_pages:
                queue.task_done()
                continue

            user_agent = headers["User-Agent"]

            async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
                respect_robot_policy = await can_fetch(session, user_agent, url)
                respect_robot_policy = True

                if respect_robot_policy:
                    html = await fetch(session, url, max_concurrent)

                    if html:
                        visited.add(url)

                        new_links = await extract_links(html, url)
                        for link in new_links:
                            if link not in visited:
                                await queue.put(link)

                        title = await get_website_title(html)
                        description = await get_website_description(html)
                        info_of_urls["url"].append(url)
                        info_of_urls["html"].append(html)
                        info_of_urls["title"].append(title)
                        info_of_urls["description"].append(description)

                        crawled_count += 1

            print(f"Crawled ({crawled_count}/{max_pages}): {url}")

            queue.task_done()
        except asyncio.CancelledError as err:
            tb = traceback.extract_tb(err.__traceback__)
            line_number = tb[-1].lineno
            print(f"CancelledError: {err} at line {line_number}")
            break
        except Exception as err:
            tb = traceback.extract_tb(err.__traceback__)
            line_number = tb[-1].lineno
            print(f"Exception: {err} at line {line_number}")

async def crawl(urls: list[str]) -> tuple[set, dict]:
    max_concurrent = 5
    total_timeout: int = 40
    visited = set()
    info_of_urls = {"url": [], "title": [], "html": [], "description": []}

    # Robots policy for Wikipedia
    # User-Agent: CoolBot/0.0 (https://example.org/coolbot/; coolbot@example.org)
    # Accept-Encoding: gzip
    headers = {"User-Agent": "CoolBot/0.0 (https://example.org/coolbot/; coolbot@example.org)", "Accept-Encoding": "gzip"}

    for start_url in urls:
        try:
            queue = asyncio.Queue()
            await queue.put(start_url)
            workers = []

            for _ in range(max_concurrent):
                worker_task = asyncio.create_task(worker(queue, visited, info_of_urls, max_concurrent, headers))
                workers.append(worker_task)

            await asyncio.wait_for(
                queue.join(),
                timeout=total_timeout
            )

            for task in workers:
                task.cancel()

            # Handle cancellations
            await asyncio.gather(*workers, return_exceptions=True)
        except asyncio.TimeoutError as err:
            tb = traceback.extract_tb(err.__traceback__)
            line_number = tb[-1].lineno
            print(f"TimeoutError: {err} at line {line_number}")
        except Exception as err:
            tb = traceback.extract_tb(err.__traceback__)
            line_number = tb[-1].lineno
            print(f"Exception: {err} at line {line_number}")

    return visited, info_of_urls

def delete_files_in_directory(directory_path: str):
    for filename in os.listdir(directory_path):
        file_path = os.path.join(directory_path, filename)
        if os.path.isfile(file_path):
            if file_path != ".gitkeep":
                os.remove(file_path)

    print(f"Deleted files in directory: {directory_path}")

async def main():
    urls = ["https://en.wikipedia.org/wiki/Main_Page", "https://example.com", "https://quotes.toscrape.com/page/1/", "https://quotes.toscrape.com/page/2/"]

    extracted_urls, info_of_urls = await crawl(urls)

    data = {
        "html_path": [],
        "title": [],
        "url": [],
        "description": []
    }

    delete_files_in_directory("data/websites")

    i = 0
    info_of_urls_df = pd.DataFrame(info_of_urls)
    for url in extracted_urls:
        result = info_of_urls_df.query(f"url == \"{url}\"")
        if not result.empty:
            title = result["title"].iloc[0]
            html = result["html"].iloc[0]
            description = result["description"].iloc[0]

            html_file_path = f"data/websites/website_{i}.html"
            with open(html_file_path, mode="w", encoding='utf-8') as f:
                    f.write(html)

            data["url"].append(url)
            data["title"].append(title)
            data["description"].append(description)
            data["html_path"].append(html_file_path)

        i += 1

    df = pd.DataFrame(data)
    df.to_csv("data/extracted_urls.csv")

if __name__ == "__main__":
    asyncio.run(main(), debug=True)
