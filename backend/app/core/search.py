"""
Web search tool wrapper.

Isolated behind a single function so the provider can be swapped
without touching graph node code.

Provider order:
1. Tavily (if TAVILY_API_KEY is set) -- recommended. Purpose-built
   search API for LLM agents, reliable on restricted networks.
2. DuckDuckGo (duckduckgo-search) -- no API key needed, but known to
   be flaky on some networks/VPNs (frequent connection timeouts).

Returns a simple list of {title, snippet, url} dicts and never raises --
failures are converted into an empty list + logged, so a flaky search
provider degrades gracefully instead of crashing a node. This feeds
directly into the data-richness conditional (route_after_research).
"""

import logging
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def web_search(query: str, max_results: int | None = None) -> list[dict]:
    """
    Run a web search and return normalized results.

    Returns: list of dicts with keys: title, snippet, url
    On failure: returns [] (low-confidence data, not a hard error).
    """
    settings = get_settings()
    n = max_results or settings.max_search_results_per_query

    if settings.tavily_api_key:
        return _tavily_search(query, n, settings.tavily_api_key)
    return _ddg_search(query, n)


def _tavily_search(query: str, n: int, api_key: str) -> list[dict]:
    try:
        from tavily import TavilyClient

        client = TavilyClient(api_key=api_key)
        response = client.search(query=query, max_results=n)

        return [
            {
                "title": r.get("title", ""),
                "snippet": r.get("content", ""),
                "url": r.get("url", ""),
            }
            for r in response.get("results", [])
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tavily search failed for query=%r: %s", query, exc)
        return []


def _ddg_search(query: str, n: int) -> list[dict]:
    try:
        from duckduckgo_search import DDGS

        with DDGS() as ddgs:
            raw_results = list(ddgs.text(query, max_results=n))

        return [
            {
                "title": r.get("title", ""),
                "snippet": r.get("body", ""),
                "url": r.get("href", ""),
            }
            for r in raw_results
        ]
    except Exception as exc:  # noqa: BLE001
        logger.warning("DDG search failed for query=%r: %s", query, exc)
        return []