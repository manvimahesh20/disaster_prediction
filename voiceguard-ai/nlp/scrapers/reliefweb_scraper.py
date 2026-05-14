"""ReliefWeb API scraper (no auth required).

Simple wrapper around ReliefWeb's public API to fetch reports matching a query.
"""
from typing import List, Dict
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _requests_session(retries: int = 2, backoff: float = 0.5, timeout: int = 10):
    s = requests.Session()
    retries = Retry(total=retries, backoff_factor=backoff, status_forcelist=(429, 500, 502, 503, 504))
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.request_timeout = timeout
    return s


def fetch_reliefweb_reports(query: str, limit: int = 20, timeout: int = 10) -> List[Dict]:
    """Fetch reports from ReliefWeb matching `query`.

    Returns a list of dicts with at least `id`, `title`, `url`, `date`.
    """
    base = "https://api.reliefweb.int/v1/reports"
    params = {"query": query, "limit": limit}
    s = _requests_session()
    resp = s.get(base, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    out: List[Dict] = []
    for item in data.get("data", []):
        fields = item.get("fields", {})
        # try to extract url
        url = None
        urls = fields.get("url") or []
        if isinstance(urls, list) and urls:
            first = urls[0]
            url = first.get("value") if isinstance(first, dict) else first

        out.append({
            "id": item.get("id") or (url or item.get("fields", {}).get("title")),
            "title": fields.get("title"),
            "summary": fields.get("body") or fields.get("description"),
            "url": url,
            "date": fields.get("date") or fields.get("posted"),
        })

    return out
