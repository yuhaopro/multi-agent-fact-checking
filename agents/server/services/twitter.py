import html
import os
import re

import httpx

_TWITTER_HOSTNAMES = {"twitter.com", "www.twitter.com", "x.com", "www.x.com"}
_SCRAPER_SUFFIX = "/twitter/tweet"
_TCO_PATTERN = re.compile(r"https://t\.co/\S+")


def _validate_twitter_url(url: str) -> None:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.hostname not in _TWITTER_HOSTNAMES:
        raise ValueError(
            f"URL must be from twitter.com or x.com, got '{parsed.hostname}'"
        )


def _expand_tco_urls(text: str, urls: list[dict]) -> str:
    """Replace t.co shortlinks in text with their expanded URLs."""
    result = text
    for entry in urls:
        short = entry.get("url", "")
        expanded = entry.get("expanded_url", short)
        if short:
            result = result.replace(short, expanded)
    return result


class Tweet:
    __slots__ = ("title", "content")

    def __init__(self, title: str, content: str) -> None:
        self.title = title
        self.content = content


async def fetch_tweet(raw_url: str) -> Tweet:
    """Fetch tweet text from the scraper API.

    Raises:
        ValueError: if the URL is not a valid Twitter/X link.
        RuntimeError: on scraper API errors or rate-limiting.
    """
    _validate_twitter_url(raw_url)

    scraper_uri = os.getenv("SCRAPER_URI", "").rstrip("/")
    api_key = os.getenv("SCRAPER_API_KEY", "")
    target = scraper_uri + _SCRAPER_SUFFIX

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            target,
            params={"url": raw_url},
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
        )

    if resp.status_code == 429:
        raise RuntimeError("Twitter/X rate limit hit — retry after a delay")
    if resp.status_code != 200:
        raise RuntimeError(f"Scraper API returned status {resp.status_code}")

    data = resp.json()
    if not data.get("success"):
        raise RuntimeError("Scraper API returned success=false for tweet")

    legacy = data.get("legacy", {})
    full_text = legacy.get("full_text", "")

    # Expand t.co shortlinks so the agent sees real URLs in the text.
    entity_urls = legacy.get("entities", {}).get("urls", [])
    full_text = _expand_tco_urls(full_text, entity_urls)

    # Build a descriptive title: @handle: <tweet text>
    screen_name = (
        data.get("core", {})
        .get("user_results", {})
        .get("result", {})
        .get("core", {})
        .get("screen_name", "")
    )
    prefix = f"@{screen_name}: " if screen_name else ""
    title = html.escape(f"{prefix}{full_text}")

    # Tweets have no separate body — the title carries the full claim text.
    return Tweet(title=title, content="")
