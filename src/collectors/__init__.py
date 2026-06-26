"""
Collectors — 信源采集模块（4 层策略）

L1  RSS:    RSS/Atom feed 采集（维护成本最低）
L2  API:    REST API / OpenAlex / Crossref
L3  Crawl:  Jina Reader / Firecrawl / BeautifulSoup
L4  Search: LLM 驱动的定向搜索（agent.py）
"""

from .base import BaseCollector, RawArticle, CollectorResult
from .rss import RSSCollector
from .scraper import ScraperCollector
from .api_client import APICollector
from .openalex import OpenAlexCollector

__all__ = [
    "BaseCollector",
    "RawArticle",
    "CollectorResult",
    "RSSCollector",
    "ScraperCollector",
    "APICollector",
    "OpenAlexCollector",
]
