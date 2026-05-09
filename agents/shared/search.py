import os
import logging

import httpx

logger = logging.getLogger(__name__)

_SEARCH_SUFFIX = "/google/search"


def fetch_search_results(query: str) -> dict:
    """Calls the external scraper service and returns raw JSON response.

    Args:
        query: The search query string.

    Returns:
        A dict with 'success' bool and 'results' list of {title, url, description}.

    Raises:
        Exception: On HTTP errors or rate limiting.
    """
    base_url = os.getenv("SCRAPER_URI", "").rstrip("/")
    api_key = os.getenv("SCRAPER_API_KEY", "")
    url = base_url + _SEARCH_SUFFIX

    with httpx.Client(timeout=10.0) as client:
        resp = client.get(
            url,
            params={"query": query},
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
        )

    if resp.status_code == 429:
        raise Exception("Google rate limit hit, retry after a delay")
    if resp.status_code != 200:
        raise Exception(f"Scraper API returned status: {resp.status_code}")

    return resp.json()
