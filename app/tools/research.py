"""Web search tool for Tier 1 enrichment.

Pluggable provider. Tavily is used when TAVILY_API_KEY / SEARCH_API_KEY is set
(reviewers bring their own key per the README). When no key is configured,
`available()` is False and search() returns [] — the enrichment agent then
degrades to clearly-flagged, source-less model knowledge instead of inventing
citations.
"""

import json
import urllib.request

from app.config import settings

TAVILY_URL = "https://api.tavily.com/search"


def available() -> bool:
    return settings.search_ready


def search(query: str, max_results: int = 5) -> list:
    """Returns [{title, url, snippet}]. Empty list if no provider or on error."""
    if not settings.search_ready:
        return []
    payload = json.dumps({
        "api_key": settings.search_api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": "basic",
    }).encode()
    req = urllib.request.Request(
        TAVILY_URL, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
    except Exception:
        return []
    return [{"title": it.get("title", ""), "url": it.get("url", ""),
             "snippet": it.get("content", "")}
            for it in data.get("results", []) if it.get("url")]
