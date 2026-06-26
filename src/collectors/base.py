"""Base collector abstract class and shared types."""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class RawArticle:
    """未处理的原始文章，来自采集器。"""

    source_id: str
    source_name: str
    url: str
    title: str
    raw_summary: str | None = None
    content: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    language: str = "en"
    image_url: str | None = None

    def compute_id(self) -> str:
        """根据 URL + 发布日期生成唯一 ID。"""
        raw = f"{self.url}|{self.published_at or ''}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class CollectorResult:
    """采集器返回结果。"""

    source_id: str
    articles: list[RawArticle] = field(default_factory=list)
    error: str | None = None
    success: bool = True


class BaseCollector(ABC):
    """采集器抽象基类。

    所有采集器必须实现 collect() 方法，返回 CollectorResult。
    """

    def __init__(self, config: dict):
        self.config = config
        self.source_id: str = config["id"]
        self.source_name: str = config.get("name", config["id"])
        self.url: str = config["url"]
        self.category: str = config.get("category", "uncategorized")
        self.language: str = config.get("language", "en")

    @abstractmethod
    def collect(self) -> CollectorResult:
        """执行采集，返回标准化文章列表。"""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.source_id})"
