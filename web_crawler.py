import asyncio
import aiohttp
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from urllib.robotparser import RobotFileParser
import pandas as pd
import os
import traceback
import ssl
import certifi
import configparser
import sys
from dataclasses import dataclass
import time
from typing import Dict

@dataclass(slots=True)  # slots reduces memory
class InfoOfUrl:
    url: str
    html: str
    title: str = ""
    description: str = ""

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

class CheckRobotsTxt:
    def __init__(self):
        self._robots_cache: Dict[str, RobotFileParser] = {}
        self._cache_lock = asyncio.Lock()

    async def can_fetch(self, session: aiohttp.ClientSession, user_agent: str, url: str) -> bool:
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        robots_url = f"{base_url}/robots.txt"

        if base_url in self._robots_cache:
            rp = self._robots_cache[base_url]
            return rp.can_fetch(user_agent, url)

        rp = RobotFileParser()
        rp.set_url(robots_url)

        try:
            async with session.get(robots_url) as response:
                if response.status == 200:
                    content = await response.text()
                    rp.parse(content.splitlines())
                elif response.status == 404:
                    return True
                else:
                    return True
        except Exception as err:
            tb = traceback.extract_tb(err.__traceback__)
            line_number = tb[-1].lineno
            print(f"Error fetching robots.txt: {err} at line {line_number}")
            return True

        self._robots_cache[base_url] = rp
        return rp.can_fetch(user_agent, url)

async def extract_links(html_content: str, current_url: str, depth: int) -> tuple[set[str], int]:
    # Slow function
    links = set()
    soup = BeautifulSoup(html_content, "lxml")
    html_links = soup.find_all('a')

    for link in html_links:
        absolute = urljoin(current_url, link.get('href'))
        parsed = urlparse(absolute)

        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.fragment:
            absolute = absolute.split("#")[0]

        links.add(absolute)

    return links, depth+1

async def get_website_title(html_content: str):
    # Slow function
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
    # Slow function
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

async def worker(queue: asyncio.Queue, visited: set, info_of_urls: list[InfoOfUrl], max_concurrent: int, headers: dict[str, str], depth: int, check_robots_txt: CheckRobotsTxt):
    max_pages=50
    crawled_count = 0
    request_timeout = 10
    max_depth = 3

    timeout = aiohttp.ClientTimeout(
            total=request_timeout,
            connect=request_timeout,
            sock_read=request_timeout
        )

    user_agent = headers["User-Agent"]

    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_context, limit=100)

    async with aiohttp.ClientSession(headers=headers, connector=connector, timeout=timeout) as session:
        while queue and crawled_count < max_pages and depth <= max_depth:
            try:
                url = await queue.get()

                if url in visited or crawled_count >= max_pages:
                    queue.task_done()
                    continue

                if depth > max_depth:
                    queue.task_done()
                    break

                start = time.perf_counter()
                respect_robot_policy = await check_robots_txt.can_fetch(session, user_agent, url)
                end = time.perf_counter()

                elapsed = end - start
                print(f"Elapsed for can_fetch: {elapsed*1000} miliseconds")

                if respect_robot_policy:
                    start = time.perf_counter()
                    html = await fetch(session, url, max_concurrent)
                    end = time.perf_counter()

                    elapsed = end - start
                    print(f"Elapsed for fetch: {elapsed*1000} miliseconds")

                    if html:
                        visited.add(url)

                        start = time.perf_counter()
                        new_links, depth = await extract_links(html, url, depth)
                        end = time.perf_counter()

                        elapsed = end - start
                        print(f"Elapsed for extract_links: {elapsed*1000} miliseconds")
                        for link in new_links:
                            if link not in visited:
                                await queue.put(link)

                        start = time.perf_counter()
                        title = await get_website_title(html)
                        end = time.perf_counter()

                        elapsed = end - start
                        print(f"Elapsed for get_website_title: {elapsed*1000} miliseconds")

                        start = time.perf_counter()
                        description = await get_website_description(html)
                        end = time.perf_counter()

                        elapsed = end - start
                        print(f"Elapsed for get_website_description: {elapsed*1000} miliseconds")
                        print("")

                        info_of_url = InfoOfUrl(url, html, title, description)
                        info_of_urls.append(info_of_url)

                        crawled_count += 1
                else:
                    print(f"Robot policy is not respected for {url}")

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

async def crawl(urls: list[str], check_robots_txt: CheckRobotsTxt) -> tuple[set, list[InfoOfUrl]]:
    max_concurrent = 10
    total_timeout: int = 40
    visited = set()
    info_of_urls = []

    # Robots policy for Wikipedia
    # User-Agent: CoolBot/0.0 (https://example.org/coolbot/; coolbot@example.org)
    # Accept-Encoding: gzip
    headers = {"User-Agent": "CoolBot/0.0 (https://example.org/coolbot/; coolbot@example.org)", "Accept-Encoding": "gzip"}

    for start_url in urls:
        depth = 0
        async with asyncio.TaskGroup() as tg:
            try:
                queue = asyncio.Queue()
                await queue.put(start_url)

                tasks = [tg.create_task(worker(queue, visited, info_of_urls, max_concurrent, headers, depth, check_robots_txt))
                             for _ in range(max_concurrent)]

                # Add a timeout to any awaitable operation
                await asyncio.wait_for(
                    # Blocks until all items in the queue have been
                    # marked as processed via task_done()
                    queue.join(),
                    timeout=total_timeout
                )

                if len(tasks) != 0:
                    # Handle cancellations
                    for task in tasks:
                        # Cancel long-running tasks and
                        # tasks that are no longer needed
                        task.cancel()

                    await asyncio.gather(*tasks, return_exceptions=True)

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

def url_in_list_of_info_urls(url: str, info_of_urls: list[InfoOfUrl]) -> tuple[bool, int]:
    for i in range(len(info_of_urls)):
        if url == info_of_urls[i].url:
            return True, i

    return False, None

async def main():
    if sys.platform == 'win32':
        loop = asyncio.get_running_loop()
        print(f"Event loop type: {type(loop)}")

    config = configparser.ConfigParser()

    ini_file = "url_seeds.ini"
    result = config.read(ini_file)

    if not result:
        print(f"Error: Could not read {ini_file}")
        exit(1)

    config.sections()

    news_urls = config['seeds:news']['urls'].split(", ")
    link_aggregator_urls = config['seeds:link_aggregators']['urls'].split(", ")
    anime_urls = config['seeds:anime']['urls'].split(", ")
    movie_urls = config['seeds:movies']['urls'].split(", ")
    tv_series_urls = config['seeds:tv_series']['urls'].split(", ")
    encyclopedia_urls = config['seeds:online_encyclopedias']['urls'].split(", ")

    urls = news_urls + link_aggregator_urls + anime_urls + movie_urls + tv_series_urls + encyclopedia_urls

    check_robots_txt = CheckRobotsTxt()

    extracted_urls, info_of_urls = await crawl(urls, check_robots_txt)

    data = {
        "html_path": [],
        "title": [],
        "url": [],
        "description": []
    }

    delete_files_in_directory("data/websites")

    i = 0
    for url in extracted_urls:
        result, j = url_in_list_of_info_urls(url, info_of_urls)
        if result:
            title = info_of_urls[j].title
            html = info_of_urls[j].html
            description = info_of_urls[j].description

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
    loop_factory=None
    if sys.platform == 'win32':
        import winloop
        loop_factory=winloop.new_event_loop
    asyncio.run(main(), loop_factory=loop_factory)
