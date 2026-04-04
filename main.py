from bs4 import BeautifulSoup
import pandas as pd

def main():
    search_query: str = input("Search query: ")

    df = pd.read_csv("data/extracted_urls.csv")

    websites = {"title": [], "url": []}

    for i in range(len(df["title"])):
        title: str = df["title"].iloc[i]
        if type(title) != float:
            if search_query.lower() in title.lower():
                url = df["url"].iloc[i]
                websites["title"].append(title)
                websites["url"].append(url)

    for i in range(len(websites)):
        print(f"Title: {websites["title"][i]}")
        print(f"URL: {websites["url"][i]}\n")

if __name__ == "__main__":
    main()