# kool_search_engine

If you hate Google search, you can always use my amazing search engine without Ads and AI.

Install dependencies
```
poetry install
```

Run the web crawler
```
poetry run python web_crawler.py
```

Run the search engine program
```
poetry run python main.py
```

Check for dependency issues
```
poetry run deptry .
```

Do not use reddit.com as a seed url. Google is the only search engine that can crawl Reddit.
- source: [Only Google Can Crawl Reddit -  Michael Tsai](https://mjtsai.com/blog/2024/07/25/only-google-can-crawl-reddit/)

Do not use imdb.com as a seed url. It does not return any HTML content. The content is dynamically generated.

Sample search terms:
1. iran war
2. trump
3. united states
4. russia
5. middle east
6. europe
7. artemis
8. frieren
9. Steel Ball Run
10. vinland saga
11. Avatar: The Last Airbender
12. Marvel's The Punisher
13. the super mario bros. movie
14. stranger things