"""Simple arXiv (papers) scraper using Atom feed queries via feedparser."""
from typing import List, Dict
import feedparser


def fetch_arxiv(query: str, max_results: int = 10) -> List[Dict]:
    """Query arXiv for papers matching `query` and return parsed entries.

    Example query: "flood OR cyclone OR earthquake"
    """
    base = "http://export.arxiv.org/api/query?"
    q = "search_query=all:(%s)" % (query.replace(" ", "+"))
    url = f"{base}{q}&start=0&max_results={max_results}"
    feed = feedparser.parse(url)
    out: List[Dict] = []
    for e in feed.entries:
        out.append(
            {
                "id": e.get("id"),
                "title": e.get("title"),
                "summary": e.get("summary"),
                "published": e.get("published"),
                "authors": [a.name for a in e.get("authors", [])],
                "link": next((l.href for l in e.get("links", []) if l.get("type") == "text/html"), e.get("id")),
            }
        )
    return out
