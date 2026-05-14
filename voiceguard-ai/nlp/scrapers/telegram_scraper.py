"""Lightweight scraper for public Telegram channels via web view.

This fetches `https://t.me/s/<channel>` and parses recent messages. No Telegram API keys required.
"""
from typing import List, Dict
import requests
from bs4 import BeautifulSoup


def fetch_telegram_channel(channel: str, limit: int = 20, timeout: int = 7) -> List[Dict]:
    """Fetch recent posts from a public Telegram channel's web view.

    `channel` should be the handle without @, e.g. 'keralaupdates'.
    """
    url = f"https://t.me/s/{channel}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    messages = soup.find_all("div", class_="tgme_widget_message")
    out: List[Dict] = []
    for m in messages[:limit]:
        text_div = m.find("div", class_="tgme_widget_message_text")
        date_a = m.find("a", class_="tgme_widget_message_date")
        msg = text_div.get_text(separator="\n").strip() if text_div else ""
        when = date_a.get_text().strip() if date_a else None
        link = date_a.get("href") if date_a and date_a.get("href") else None
        out.append({
            "id": link or (channel + ":" + (when or "")),
            "channel": channel,
            "text": msg,
            "date": when,
            "url": link,
        })
    return out
