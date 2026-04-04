import asyncio
import aiohttp
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from urllib.robotparser import RobotFileParser


async def fetch(session: aiohttp.ClientSession, url: str, max_concurrent: int) -> str:
    semaphore = asyncio.Semaphore(max_concurrent)
    async with semaphore:
        try:
            async with session.get(url, timeout=10) as response:
                html = await response.text()
                return html
        except Exception as e:
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
    except Exception as e:
        print(f"Error fetching robots.txt: {e}")
        return False
    
    return rp.can_fetch(user_agent, url)

async def extract_links(html: str, current_url: str) -> Set[str]:
    links = set()

    soup = BeautifulSoup(html, 'lxml')

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

async def worker(queue: asyncio.Queue, visited: set, max_concurrent: int, headers: dict[str, str]):
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
                        
                        crawled_count += 1
                
            print(f"Crawled ({crawled_count}/{max_pages}): {url}")
            
            queue.task_done()
        except asyncio.CancelledError:
            break
        except Exception as err:
            print(f"Exception: {err}")

async def crawl(urls: list[str]):
    max_concurrent = 5
    total_timeout: int = 40
    visited = set()

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
                worker_task = asyncio.create_task(worker(queue, visited, max_concurrent, headers))
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
            print(f"TimeoutError: {err}")
        except Exception as err:
            print(f"Exception: {err}")
        
    return visited

async def main():
    urls = ["https://en.wikipedia.org/wiki/Main_Page", "https://example.com", "https://quotes.toscrape.com/page/1/", "https://quotes.toscrape.com/page/2/"]
    
    extracted_urls = await crawl(urls)
    print(extracted_urls)

if __name__ == "__main__":
    asyncio.run(main(), debug=True)
