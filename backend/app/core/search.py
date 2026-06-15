"""
Web search tool wrapper.

Isolated behind a single function so the provider (DuckDuckGo, Tavily,
SerpAPI, ...) can be swapped without touching graph node code.
Returns a simple list of {title, snippet, url} dicts and never raises --
failures are converted into an empty list + logged, so a flaky search
provider degrades gracefully instead of crashing a node.
"""

import logging
from app.core.config import get_settings

logger = logging.getLogger(__name__)


def web_search(query: str, max_results: int | None = None) -> list[dict]:
    """
    Run a web search and return normalized results.

    Returns: list of dicts with keys: title, snippet, url
    On failure: returns [] (caller treats this as low-confidence data,
    not a hard error -- this is what feeds the data-richness conditional).
    """
    settings = get_settings()
    n = max_results or settings.max_search_results_per_query

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

    except Exception as exc:  # noqa: BLE001 - intentional broad catch
        logger.warning("web_search failed for query=%r: %s", query, exc)
        return []
