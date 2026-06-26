"""RSS/Atom feed collector."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from time import struct_time

import feedparser
import httpx

from .base import BaseCollector, CollectorResult, RawArticle

logger = logging.getLogger(__name__)


def _parse_date(struct: struct_time | str | None) -> datetime | None:
    """尝试多种方式解析 RSS 日期。"""
    if struct is None:
        return None
    if isinstance(struct, struct_time):
        return datetime(*struct[:6], tzinfo=timezone.utc)
    if isinstance(struct, str):
        try:
            return parsedate_to_datetime(struct)
        except (ValueError, TypeError):
            pass
    return None


class RSSCollector(BaseCollector):
    """RSS/Atom feed 通用采集器。

    Config keys:
        - url: RSS feed URL
        - max_articles: 每次最多采集文章数 (默认 50)
        - user_agent: 自定义 User-Agent
    """

    def collect(self) -> CollectorResult:
        url = self.url
        max_articles = self.config.get("max_articles", 50)
        user_agent = self.config.get("user_agent", "FisheryNewsBot/0.1")
        timeout = self.config.get("timeout", 30)

        try:
            # 先用 httpx 获取 feed 内容，再交给 feedparser 解析
            response = httpx.get(
                url,
                headers={"User-Agent": user_agent},
                timeout=timeout,
                follow_redirects=True,
            )
            response.raise_for_status()

            # 尝试清理常见 XML 问题（unbound prefix 等）
            xml_text = response.text
            feed = feedparser.parse(xml_text)

            # 如果解析失败，尝试修复常见问题
            if feed.bozo and not feed.entries:
                xml_text = self._sanitize_xml(xml_text)
                if xml_text != response.text:
                    logger.debug(f"[{self.source_id}] Retrying with sanitized XML")
                    feed = feedparser.parse(xml_text)

            if feed.bozo and not feed.entries:
                return CollectorResult(
                    source_id=self.source_id,
                    success=False,
                    error=f"Feed parse error: {feed.bozo_exception}",
                )

            articles = []
            for entry in feed.entries[:max_articles]:
                published = (
                    _parse_date(entry.get("published_parsed"))
                    or _parse_date(entry.get("updated_parsed"))
                    or _parse_date(entry.get("published"))
                )

                # 提取链接
                link = entry.get("link", "")
                if not link and entry.get("links"):
                    link = entry.links[0].get("href", "")

                # 提取摘要
                summary = entry.get("summary") or entry.get("description", "")
                # 清理 HTML 标签（简单版）
                if summary:
                    import re
                    summary = re.sub(r"<[^>]+>", "", summary).strip()

                article = RawArticle(
                    source_id=self.source_id,
                    source_name=self.source_name,
                    url=link,
                    title=entry.get("title", "Untitled").strip(),
                    raw_summary=summary[:500] if summary else None,
                    content=entry.get("content", [{}])[0].get("value", None) if entry.get("content") else None,
                    author=entry.get("author"),
                    published_at=published,
                    language=self.language,
                    image_url=entry.get("media_content", [{}])[0].get("url", None) if entry.get("media_content") else None,
                )
                articles.append(article)

            logger.info(
                f"[{self.source_id}] Collected {len(articles)} articles from {url}"
            )
            return CollectorResult(source_id=self.source_id, articles=articles)

        except httpx.HTTPError as e:
            logger.error(f"[{self.source_id}] HTTP error: {e}")
            return CollectorResult(source_id=self.source_id, success=False, error=str(e))
        except Exception as e:
            logger.exception(f"[{self.source_id}] Unexpected error: {e}")
            return CollectorResult(source_id=self.source_id, success=False, error=str(e))

    @staticmethod
    def _sanitize_xml(xml_text: str) -> str:
        """清理常见的 XML 问题（unbound prefix, invalid tokens 等）。"""
        import re

        # 移除未绑定的命名空间前缀（如 <dc:creator> 但未声明 dc 命名空间）
        known_prefixes = ["dc:", "content:", "media:", "sy:", "slash:", "wfw:", "georss:", "gml:"]
        for prefix in known_prefixes:
            escaped_prefix = re.escape(prefix)
            # 移除开标签中的前缀
            xml_text = re.sub(
                "<" + escaped_prefix + r"(\w+)",
                r"<\1",
                xml_text,
            )
            # 移除闭标签中的前缀
            xml_text = re.sub(
                "</" + escaped_prefix + r"(\w+)",
                r"</\1",
                xml_text,
            )

        # 移除 XML 声明前的空白字符
        xml_text = xml_text.strip()

        # 移除非法的 XML 字符
        xml_text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", xml_text)

        return xml_text
