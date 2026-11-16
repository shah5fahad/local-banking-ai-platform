"""Search provider integration: Serper and Tavily with allow-list enforcement."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import requests

from app.core.config import AISettings

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Standardized web search result."""

    title: str
    url: str
    snippet: str
    domain: str


def extract_domain(url: str) -> str:
    """Extract lowercase hostname/domain from a URL."""
    try:
        netloc = urlparse(url).netloc.lower().strip()
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        return netloc
    except Exception:
        return ""


def is_domain_allowed(domain: str, allowed_domains_csv: str) -> bool:
    """Check if domain is permitted by the comma-separated allowed_domains list.

    If allowed_domains_csv is empty, all domains are allowed.
    Supports exact match or subdomain matching (e.g. 'news.bbc.co.uk' matches 'bbc.co.uk').
    """
    if not allowed_domains_csv or not allowed_domains_csv.strip():
        return True

    clean_domain = domain.strip().lower()
    if ":" in clean_domain:
        clean_domain = clean_domain.split(":")[0]

    if not clean_domain:
        return False

    allowed_list = [
        d.strip().lower() for d in allowed_domains_csv.split(",") if d.strip()
    ]
    if not allowed_list:
        return True

    for allowed in allowed_list:
        if clean_domain == allowed or clean_domain.endswith("." + allowed):
            return True

    return False


def search_web(
    query: str,
    settings: AISettings,
    top_n: int = 5,
) -> list[SearchResult]:
    """Execute a web search using the configured provider and filter by allowed domains.

    Returns an empty list on errors or when provider is 'none'.
    """
    if not query or not query.strip():
        return []

    provider = (settings.search_provider or "none").strip().lower()
    if provider == "none":
        return []

    try:
        results: list[SearchResult] = []

        if provider == "serper":
            if not settings.search_api_key:
                logger.warning("Serper search provider configured without search_api_key")
                return []

            resp = requests.post(
                "https://google.serper.dev/search",
                headers={
                    "X-API-KEY": settings.search_api_key,
                    "Content-Type": "application/json",
                },
                json={"q": query.strip(), "num": max(top_n * 2, 10)},
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            organic = data.get("organic", [])

            for item in organic:
                link = item.get("link") or item.get("url") or ""
                domain = extract_domain(link)
                if is_domain_allowed(domain, settings.search_allowed_domains):
                    results.append(
                        SearchResult(
                            title=item.get("title", ""),
                            url=link,
                            snippet=item.get("snippet", ""),
                            domain=domain,
                        )
                    )
                    if len(results) >= top_n:
                        break

            return results

        elif provider == "tavily":
            if not settings.search_api_key:
                logger.warning("Tavily search provider configured without search_api_key")
                return []

            resp = requests.post(
                "https://api.tavily.com/search",
                headers={"Content-Type": "application/json"},
                json={
                    "api_key": settings.search_api_key,
                    "query": query.strip(),
                    "max_results": max(top_n * 2, 10),
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            raw_results = data.get("results", [])

            for item in raw_results:
                link = item.get("url") or item.get("link") or ""
                domain = extract_domain(link)
                if is_domain_allowed(domain, settings.search_allowed_domains):
                    results.append(
                        SearchResult(
                            title=item.get("title", ""),
                            url=link,
                            snippet=item.get("content") or item.get("snippet") or "",
                            domain=domain,
                        )
                    )
                    if len(results) >= top_n:
                        break

            return results

        else:
            logger.warning("Unsupported search provider: %s", provider)
            return []

    except Exception as exc:
        logger.warning("Web search error: %s", exc)
        return []
