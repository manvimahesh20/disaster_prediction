# Scrapers

This package provides simple scrapers for Reddit (using PRAW), Twitter (Tweepy v2), and Instagram (Instaloader).

Setup

1. Create a virtual environment and install dependencies:

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r disaster_prediction/voiceguard-ai/nlp/scrapers/requirements.txt
```

2. Copy `.env.example` to `.env` and fill credentials, or set the environment variables directly.

Usage examples

Google News RSS feeds:

```py
from voiceguard_ai.nlp.scrapers.rss_scraper import fetch_feeds

feeds = [
	"https://news.google.com/rss/search?q=Kerala+flood",
	"https://news.google.com/rss/search?q=Kerala",
]
posts = fetch_feeds(feeds, limit_per_feed=10)
```

ReliefWeb API:

```py
from voiceguard_ai.nlp.scrapers.reliefweb_scraper import fetch_reliefweb_reports

reports = fetch_reliefweb_reports("Kerala flood", limit=20)
```

Telegram public channels (web view):

```py
from voiceguard_ai.nlp.scrapers.telegram_scraper import fetch_telegram_channel

posts = fetch_telegram_channel("kerala_updates", limit=20)
```

arXiv (papers):

```py
from voiceguard_ai.nlp.scrapers.arxiv_scraper import fetch_arxiv

papers = fetch_arxiv("flood OR cyclone OR earthquake", max_results=20)
```

Twitter:

```py
from voiceguard_ai.nlp.scrapers.twitter_scraper import search_recent_tweets

tweets = search_recent_tweets("Kerala flood", max_results=50)
```

Instagram:

```py
from voiceguard_ai.nlp.scrapers.instagram_scraper import fetch_hashtag_posts

posts = fetch_hashtag_posts("Kerala", limit=30, login=False)
```

Notes

- Twitter API v2 requires appropriate access and credentials.
- Instagram scraping via Instaloader may require login for larger or age-restricted results.
- Respect each service's terms of use and rate limits.
