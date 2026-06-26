"""REST API collector client."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from .base import BaseCollector, CollectorResult, RawArticle

logger = logging.getLogger(__name__)


class APICollector(BaseCollector):
    """REST API 采集器。

    Config keys:
        - url: API endpoint URL
        - method: HTTP method (GET, POST; 默认 GET)
        - headers: 额外请求头
        - params: 查询参数
        - body: POST body
        - response_path: JSON 响应中文章列表的路径 (用 "." 分隔, 如 "data.items")
        - field_map: 响应字段映射
            {article_field: json_field_path}
            支持: title, url, summary, content, author, published_at, image_url
        - max_articles: 最多采集数
        - user_agent: 自定义 UA
        - timeout: 超时秒数
    """

    def collect(self) -> CollectorResult:
        url = self.url
        method = self.config.get("method", "GET").upper()
        headers = {"User-Agent": self.config.get("user_agent", "FisheryNewsBot/0.1")}
        if extra_headers := self.config.get("headers"):
            headers.update(extra_headers)
        params = self.config.get("params", {})
        body = self.config.get("body")
        response_path = self.config.get("response_path", "")
        field_map = self.config.get("field_map", {})
        max_articles = self.config.get("max_articles", 50)
        timeout = self.config.get("timeout", 30)

        try:
            kwargs = {"headers": headers, "timeout": timeout, "params": params}
            if body and method == "POST":
                kwargs["json"] = body

            response = httpx.request(method, url, **kwargs)
            response.raise_for_status()

            data = response.json()

            # 定位文章列表
            items = data
            if response_path:
                for key in response_path.split("."):
                    if isinstance(items, dict):
                        items = items.get(key, [])
                    elif isinstance(items, list) and key.isdigit():
                        items = items[int(key)]
                    else:
                        items = []
                        break

            if not isinstance(items, list):
                items = [items] if items else []

            articles = []
            for item in items[:max_articles]:
                if not isinstance(item, dict):
                    continue

                article = RawArticle(
                    source_id=self.source_id,
                    source_name=self.source_name,
                    url=self._get_field(item, field_map, "url", ""),
                    title=self._get_field(item, field_map, "title", "Untitled"),
                    raw_summary=self._get_field(item, field_map, "summary"),
                    content=self._get_field(item, field_map, "content"),
                    author=self._get_field(item, field_map, "author"),
                    published_at=self._parse_api_date(
                        self._get_field(item, field_map, "published_at")
                    ),
                    language=self.language,
                    image_url=self._get_field(item, field_map, "image_url"),
                )

                if article.url and article.title:
                    articles.append(article)

            logger.info(f"[{self.source_id}] API collected {len(articles)} articles from {url}")
            return CollectorResult(source_id=self.source_id, articles=articles)

        except httpx.HTTPError as e:
            logger.error(f"[{self.source_id}] HTTP error: {e}")
            return CollectorResult(source_id=self.source_id, success=False, error=str(e))
        except Exception as e:
            logger.exception(f"[{self.source_id}] Unexpected error: {e}")
            return CollectorResult(source_id=self.source_id, success=False, error=str(e))

    @staticmethod
    def _get_field(
        item: dict, field_map: dict, field_name: str, default: str | None = None
    ) -> str | None:
        """根据 field_map 从 JSON 对象中提取字段。"""
        if field_name in field_map:
            path = field_map[field_name]
            value = item
            for key in path.split("."):
                if isinstance(value, dict):
                    value = value.get(key)
                else:
                    return default
            return str(value) if value else default

        # 默认: 直接用 field_name 作为 key
        value = item.get(field_name)
        return str(value) if value else default

    @staticmethod
    def _parse_api_date(text: str | None) -> datetime | None:
        """解析 API 返回的日期字符串。"""
        if not text:
            return None
        from dateutil.parser import parse as dateutil_parse

        try:
            return dateutil_parse(text)
        except (ValueError, TypeError):
            pass
        return None
