from bs4 import BeautifulSoup
import pandas as pd

def main():
    while True:
        search_query: str = input("Search query (Quit with q!): ")
        df = pd.read_csv("data/extracted_urls.csv")
        websites = {"title": [], "url": [], "description": []}

        if search_query == "q!":
            break

        for i in range(len(df["title"])):
            title: str = df["title"].iloc[i]
            description: str = df["description"].iloc[i]
            html_path: str = df["html_path"].iloc[i]
            url: str = df["url"].iloc[i]

            if type(title) == str:
                if search_query.lower() in title.lower():
                    websites["title"].append(title)
                    websites["url"].append(url)
                    websites["description"].append(description)
            elif type(title) != str:
                title = "Untitled"
            elif type(description) == str:
                if search_query.lower() in description.lower():
                    websites["title"].append(title)
                    websites["url"].append(url)
                    websites["description"].append(description)
            else:
                with open(html_path, "r", encoding='utf-8') as f:
                    html = f.read()
                    soup = BeautifulSoup(html, 'lxml')

                    if soup.body is not None:
                        result = soup.body.find(string=search_query.lower())
                        if result is not None:
                            websites["title"].append(title)
                            websites["url"].append(url)
                            websites["description"].append(description)

        for i in range(len(websites["title"])):
            print(f"Title: {websites["title"][i]}")
            print(f"URL: {websites["url"][i]}")
            print(f"Description: {websites["description"][i]}\n")

if __name__ == "__main__":
    main()