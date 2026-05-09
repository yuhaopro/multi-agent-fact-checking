import html
import os
from urllib.parse import urlparse, urlunparse

import httpx

_REDDIT_HOSTNAME = "www.reddit.com"
_SCRAPER_SUFFIX = "/reddit/post/comments"


def _normalize_reddit_url(url: str) -> str:
    """Validate that the URL is a Reddit link and return its .json variant."""
    parsed = urlparse(url)
    if parsed.hostname != _REDDIT_HOSTNAME:
        raise ValueError(f"URL must be from {_REDDIT_HOSTNAME}, got '{parsed.hostname}'")

    path = parsed.path
    if not path.endswith(".json"):
        path += ".json"

    return urlunparse(("https", parsed.netloc, path, "", parsed.query, ""))


class RedditPost:
    __slots__ = ("title", "content")

    def __init__(self, title: str, content: str) -> None:
        self.title = title
        self.content = content


async def fetch_reddit_post(raw_url: str) -> RedditPost:
    """Fetch post title and selftext from the scraper API.

    Raises:
        ValueError: if the URL is not a valid Reddit link.
        RuntimeError: on scraper API errors or rate-limiting.
    """
    json_url = _normalize_reddit_url(raw_url)

    scraper_uri = os.getenv("SCRAPER_URI", "").rstrip("/")
    api_key = os.getenv("SCRAPER_API_KEY", "")
    target = scraper_uri + _SCRAPER_SUFFIX

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            target,
            params={"url": json_url},
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
        )

    if resp.status_code == 429:
        raise RuntimeError("Reddit rate limit hit — retry after a delay")
    if resp.status_code != 200:
        raise RuntimeError(f"Scraper API returned status {resp.status_code}")

    data = resp.json()
    post_data = data.get("post", {})

    # Escape HTML characters to prevent stored-XSS when content is later rendered.
    return RedditPost(
        title=html.escape(post_data.get("title", "")),
        content=html.escape(post_data.get("selftext", "")),
    )
