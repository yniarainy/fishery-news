"""Pydantic data models for the fishery news system."""

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class RawArticle(BaseModel):
    """未处理的原始文章，来自采集器。"""

    source_id: str = Field(..., description="sources.yaml 中的信源 ID")
    source_name: str = Field(..., description="信源名称")
    url: str = Field(..., description="文章 URL")
    title: str = Field(..., description="文章标题")
    raw_summary: Optional[str] = Field(default=None, description="原文导语/摘要")
    content: Optional[str] = Field(default=None, description="全文内容")
    author: Optional[str] = Field(default=None, description="作者")
    published_at: Optional[datetime] = Field(default=None, description="发布时间")
    language: str = Field(default="en", description="语言代码")
    image_url: Optional[str] = Field(default=None, description="配图 URL")

    def compute_id(self) -> str:
        """根据 URL + 发布日期生成唯一 ID。"""
        raw = f"{self.url}|{self.published_at or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


class Article(BaseModel):
    """处理后的文章记录（对应 SQLite articles 表）。"""

    id: str = Field(..., description="sha256(url+date)[:16]")
    source_id: str
    source_name: str = ""
    url: str
    title: str
    raw_summary: Optional[str] = None
    content: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=datetime.now)
    language: str = "en"
    image_url: Optional[str] = None

    # LLM 处理后填充
    category: Optional[str] = None  # policy/science/industry/ngo/data
    summary_cn: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    entities: Dict[str, List[str]] = Field(default_factory=dict)
    embedding_id: Optional[str] = None
    cluster_id: Optional[str] = None
    is_duplicate: bool = False
    duplicate_of: Optional[str] = None

    # 周刊归属
    issue_number: Optional[str] = None  # "2026-W26"
    included_in_issue: bool = False

    class Config:
        from_attributes = True


class Issue(BaseModel):
    """周刊记录（对应 SQLite issues 表）。"""

    number: str = Field(..., description="周刊编号，如 2026-W26")
    title: str = ""
    period_start: str = ""  # YYYY-MM-DD
    period_end: str = ""
    markdown_path: Optional[str] = None
    html_path: Optional[str] = None
    wechat_media_id: Optional[str] = None
    notion_page_id: Optional[str] = None
    article_count: int = 0
    published_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)

    class Config:
        from_attributes = True


class SourceHealth(BaseModel):
    """信源健康状态（对应 SQLite source_health 表）。"""

    source_id: str = Field(..., description="sources.yaml 中的信源 ID")
    last_success: Optional[datetime] = None
    last_failure: Optional[datetime] = None
    error_count: int = 0
    articles_collected: int = 0
    status: str = "active"  # active / error / disabled
    last_error: Optional[str] = None

    class Config:
        from_attributes = True


class ClusterGroup(BaseModel):
    """一组聚类后的相关文章。"""

    cluster_id: str
    articles: List[Article]
    main_article: Optional[Article] = None  # 代表文章
    topic: str = ""  # LLM 生成的话题标签
    combined_summary: str = ""  # LLM 综合摘要


class NewsletterData(BaseModel):
    """周刊渲染所需的全部数据。"""

    issue: Issue
    articles: List[Article]
    clusters: List[ClusterGroup] = Field(default_factory=list)
    weekly_insight: Dict[str, Any] = Field(default_factory=dict)
    category_distribution: Dict[str, int] = Field(default_factory=dict)
    top_articles: List[Article] = Field(default_factory=list)
    hot_topics: List[str] = Field(default_factory=list)
