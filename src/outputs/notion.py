"""Notion publisher — write newsletter content to Notion database."""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from src.storage.models import Issue

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionPublisher:
    """Notion 发布器。

    将每期周刊的文章写入 Notion 数据库，每条新闻一个 page。
    同时创建一个周刊总结 page。

    Notion API 参考: https://developers.notion.com/reference
    """

    def __init__(self, config: dict):
        notion_config = config.get("notion", {})
        self.api_key = notion_config.get("api_key", "")
        self.database_id = notion_config.get("database_id", "")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Notion-Version": NOTION_VERSION,
        }

    def publish(
        self,
        markdown_content: str,
        issue: Issue,
        articles: list | None = None,
    ) -> dict:
        """将周刊内容发布到 Notion。

        Args:
            markdown_content: 周刊 Markdown
            issue: 周刊信息
            articles: 文章列表

        Returns:
            {"weekly_page_id": "...", "article_page_ids": [...]}
        """
        if not self.api_key or not self.database_id:
            raise RuntimeError("Notion API key or database ID not configured")

        result = {}

        # 1. 创建周刊总结 page
        weekly_page_id = self._create_weekly_page(issue, markdown_content)
        result["weekly_page_id"] = weekly_page_id

        # 2. 逐篇文章创建 page
        if articles:
            article_ids = []
            for article in articles:
                try:
                    page_id = self._create_article_page(article, issue.number)
                    if page_id:
                        article_ids.append(page_id)
                except Exception as e:
                    logger.error(f"[Notion] Failed to create page for '{article.title[:40]}...': {e}")

            result["article_page_ids"] = article_ids
            logger.info(f"[Notion] Created {len(article_ids)} article pages")

        return result

    def _create_weekly_page(self, issue: Issue, markdown: str) -> str | None:
        """创建周刊总结 page。"""
        url = f"{NOTION_API_BASE}/pages"

        # 将 Markdown 转为 Notion blocks
        children = self._markdown_to_notion_blocks(markdown)

        data = {
            "parent": {"database_id": self.database_id},
            "properties": {
                "Name": {
                    "title": [{"text": {"content": f"📰 {issue.title}"}}]
                },
                "Type": {
                    "select": {"name": "Weekly"}
                },
                "Issue Number": {
                    "number": issue.number
                },
                "Date": {
                    "date": {"start": issue.period_start, "end": issue.period_end}
                },
                "Articles Count": {
                    "number": issue.article_count
                },
            },
            "children": children[:100],  # Notion 限制最多 100 blocks
        }

        try:
            resp = httpx.post(url, headers=self.headers, json=data, timeout=30)
            resp.raise_for_status()
            page_id = resp.json()["id"]
            logger.info(f"[Notion] Weekly page created: {page_id}")
            return page_id
        except httpx.HTTPError as e:
            logger.error(f"[Notion] Failed to create weekly page: {e}")
            if e.response:
                logger.error(f"[Notion] Response: {e.response.text[:500]}")
            return None

    def _create_article_page(self, article, issue_number: int) -> str | None:
        """创建单篇文章 page。"""
        url = f"{NOTION_API_BASE}/pages"

        category = getattr(article, '_cached_category', 'industry') or 'industry'
        summary = getattr(article, '_cached_summary', '') or ''
        tags = getattr(article, '_cached_tags', []) or []
        entities = getattr(article, '_cached_entities', {}) or {}

        # Notion 属性
        properties = {
            "Name": {
                "title": [{"text": {"content": article.title[:100]}}]
            },
            "URL": {
                "url": article.url
            },
            "Source": {
                "select": {"name": article.source_name}
            },
            "Category": {
                "select": {"name": category}
            },
            "Issue Number": {
                "number": issue_number
            },
        }

        if article.published_at:
            properties["Published Date"] = {
                "date": {"start": article.published_at.strftime("%Y-%m-%d")}
            }

        # Notion blocks
        children = []
        if summary:
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"📝 {summary}"}}
                    ]
                }
            })

        if tags:
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"🏷️ {' · '.join(tags[:10])}"}}
                    ]
                }
            })

        if entities.get("species"):
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"🐟 物种: {', '.join(entities['species'][:5])}"}}
                    ]
                }
            })

        if entities.get("regions"):
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [
                        {"type": "text", "text": {"content": f"🌍 区域: {', '.join(entities['regions'][:5])}"}}
                    ]
                }
            })

        children.append({
            "object": "block",
            "type": "bookmark",
            "bookmark": {
                "url": article.url,
                "caption": [{"type": "text", "text": {"content": "阅读原文"}}]
            }
        })

        data = {
            "parent": {"database_id": self.database_id},
            "properties": properties,
            "children": children,
        }

        try:
            resp = httpx.post(url, headers=self.headers, json=data, timeout=15)
            resp.raise_for_status()
            return resp.json()["id"]
        except httpx.HTTPError as e:
            logger.error(f"[Notion] Article page error: {e}")
            return None

    def _markdown_to_notion_blocks(self, markdown: str) -> list[dict]:
        """将 Markdown 转为 Notion block 数组（简化版）。"""
        blocks = []
        lines = markdown.split("\n")
        in_code = False

        for line in lines[:200]:  # 限制行数
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue

            stripped = line.strip()
            if not stripped:
                continue

            # 标题
            if stripped.startswith("# ") and not stripped.startswith("## "):
                text = stripped[2:]
                blocks.append({
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {
                        "rich_text": [{"type": "text", "text": {"content": text[:100]}}]
                    }
                })
            elif stripped.startswith("## "):
                text = stripped[3:]
                blocks.append({
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"type": "text", "text": {"content": text[:100]}}]
                    }
                })
            elif stripped.startswith("### "):
                text = stripped[4:]
                blocks.append({
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [{"type": "text", "text": {"content": text[:100]}}]
                    }
                })
            elif stripped == "---":
                blocks.append({
                    "object": "block",
                    "type": "divider",
                    "divider": {}
                })
            elif stripped.startswith("- "):
                text = stripped[2:][:500]
                blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"type": "text", "text": {"content": text}}]
                    }
                })
            else:
                text = stripped[:500]
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": text}}]
                    }
                })

        return blocks[:100]  # Notion 限制
