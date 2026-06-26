"""SQLite database layer for fishery news metadata."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import Article, Issue, SourceHealth


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS articles (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    source_name TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    raw_summary TEXT,
    content TEXT,
    author TEXT,
    published_at TEXT,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    language TEXT NOT NULL DEFAULT 'en',
    image_url TEXT,

    -- LLM 处理结果
    category TEXT,
    summary_cn TEXT,
    tags TEXT DEFAULT '[]',
    entities TEXT DEFAULT '{}',
    embedding_id TEXT,
    cluster_id TEXT,
    is_duplicate INTEGER DEFAULT 0,
    duplicate_of TEXT,

    -- 周刊归属
    issue_number TEXT,                                   -- "2026-W26"
    included_in_issue INTEGER DEFAULT 0,

    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_articles_url ON articles(url);
CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source_id);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
CREATE INDEX IF NOT EXISTS idx_articles_issue ON articles(issue_number);
CREATE INDEX IF NOT EXISTS idx_articles_duplicate ON articles(is_duplicate);
CREATE INDEX IF NOT EXISTS idx_articles_cluster ON articles(cluster_id);

CREATE TABLE IF NOT EXISTS issues (
    number TEXT PRIMARY KEY,                             -- e.g. "2026-W26"
    title TEXT NOT NULL DEFAULT '',
    period_start TEXT NOT NULL DEFAULT '',
    period_end TEXT NOT NULL DEFAULT '',
    markdown_path TEXT,
    html_path TEXT,
    wechat_media_id TEXT,
    notion_page_id TEXT,
    article_count INTEGER DEFAULT 0,
    published_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS source_health (
    source_id TEXT PRIMARY KEY,
    last_success TEXT,
    last_failure TEXT,
    error_count INTEGER DEFAULT 0,
    articles_collected INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    last_error TEXT
);
"""


class Database:
    """SQLite 数据库操作封装。"""

    def __init__(self, db_path: str | Path = "data/fishery_news.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA)
        return self._conn

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ---- Article CRUD ----

    def insert_article(self, article: Article) -> bool:
        """Insert or ignore article (skip if id already exists)."""
        sql = """
        INSERT OR IGNORE INTO articles
            (id, source_id, source_name, url, title, raw_summary, content,
             author, published_at, language, image_url,
             category, summary_cn, tags, entities, embedding_id, cluster_id,
             is_duplicate, duplicate_of, issue_number, included_in_issue)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            self.conn.execute(sql, (
                article.id,
                article.source_id,
                article.source_name,
                article.url,
                article.title,
                article.raw_summary,
                article.content,
                article.author,
                article.published_at.isoformat() if article.published_at else None,
                article.language,
                article.image_url,
                article.category,
                article.summary_cn,
                json.dumps(article.tags, ensure_ascii=False),
                json.dumps(article.entities, ensure_ascii=False),
                article.embedding_id,
                article.cluster_id,
                int(article.is_duplicate),
                article.duplicate_of,
                article.issue_number,
                int(article.included_in_issue),
            ))
            self.conn.commit()
            return True
        except Exception:
            return False

    def update_article(self, article_id: str, **kwargs) -> bool:
        """Update article fields by keyword arguments."""
        if not kwargs:
            return False
        # JSON-serialize list/dict fields
        for json_field in ("tags", "entities"):
            if json_field in kwargs and isinstance(kwargs[json_field], (list, dict)):
                kwargs[json_field] = json.dumps(kwargs[json_field], ensure_ascii=False)
        # Bool to int
        for bool_field in ("is_duplicate", "included_in_issue"):
            if bool_field in kwargs:
                kwargs[bool_field] = int(kwargs[bool_field])

        set_clause = ", ".join(f"{k}=?" for k in kwargs)
        values = list(kwargs.values()) + [article_id]
        try:
            self.conn.execute(f"UPDATE articles SET {set_clause} WHERE id=?", values)
            self.conn.commit()
            return True
        except Exception:
            return False

    def article_exists(self, url: str) -> bool:
        """Check if a URL has already been collected."""
        row = self.conn.execute("SELECT 1 FROM articles WHERE url=? LIMIT 1", (url,)).fetchone()
        return row is not None

    def get_article(self, article_id: str) -> Article | None:
        return self._row_to_article(
            self.conn.execute("SELECT * FROM articles WHERE id=?", (article_id,)).fetchone()
        )

    def get_articles_by_source(self, source_id: str, limit: int = 50) -> list[Article]:
        rows = self.conn.execute(
            "SELECT * FROM articles WHERE source_id=? ORDER BY published_at DESC LIMIT ?",
            (source_id, limit),
        ).fetchall()
        return [self._row_to_article(r) for r in rows if r]

    def get_recent_articles(
        self, days: int = 30, exclude_duplicates: bool = True
    ) -> list[Article]:
        """Get articles from the last N days."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        sql = "SELECT * FROM articles WHERE published_at >= ?"
        if exclude_duplicates:
            sql += " AND is_duplicate = 0"
        sql += " ORDER BY published_at DESC"
        rows = self.conn.execute(sql, (cutoff,)).fetchall()
        return [self._row_to_article(r) for r in rows if r]

    def get_articles_without_category(self, limit: int = 100) -> list[Article]:
        rows = self.conn.execute(
            "SELECT * FROM articles WHERE category IS NULL AND is_duplicate=0 LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_article(r) for r in rows if r]

    def get_articles_without_summary(self, limit: int = 100) -> list[Article]:
        rows = self.conn.execute(
            "SELECT * FROM articles WHERE summary_cn IS NULL AND is_duplicate=0 LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._row_to_article(r) for r in rows if r]

    def get_articles_by_issue(self, issue_number: str) -> list[Article]:
        rows = self.conn.execute(
            "SELECT * FROM articles WHERE issue_number=? AND included_in_issue=1 ORDER BY category, published_at DESC",
            (issue_number,),
        ).fetchall()
        return [self._row_to_article(r) for r in rows if r]

    def get_recent_urls(self, days: int = 30) -> set[str]:
        """Get all URLs collected in the last N days (for quick dedup)."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            "SELECT url FROM articles WHERE fetched_at >= ?", (cutoff,)
        ).fetchall()
        return {r["url"] for r in rows}

    def get_published_urls(self, days: int = 90) -> set[str]:
        """Get URLs already included in a published issue (for dedup across issues).
        Only deduplicates articles that were actually published, not just fetched.
        This allows re-running the pipeline during development without losing content.
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            "SELECT url FROM articles WHERE included_in_issue = 1 AND fetched_at >= ?",
            (cutoff,),
        ).fetchall()
        return {r["url"] for r in rows}

    # ---- Issue CRUD ----

    def get_latest_issue_number(self) -> str:
        row = self.conn.execute("SELECT MAX(number) FROM issues").fetchone()
        return row[0] or ""

    def create_issue(self, issue: Issue) -> bool:
        sql = """
        INSERT OR REPLACE INTO issues
            (number, title, period_start, period_end, markdown_path, html_path,
             wechat_media_id, notion_page_id, article_count, published_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            self.conn.execute(sql, (
                issue.number,
                issue.title,
                issue.period_start,
                issue.period_end,
                issue.markdown_path,
                issue.html_path,
                issue.wechat_media_id,
                issue.notion_page_id,
                issue.article_count,
                issue.published_at.isoformat() if issue.published_at else None,
            ))
            self.conn.commit()
            return True
        except Exception:
            return False

    def get_issue(self, number: str) -> Issue | None:
        row = self.conn.execute("SELECT * FROM issues WHERE number=?", (number,)).fetchone()
        if not row:
            return None
        return Issue(
            number=row["number"],
            title=row["title"],
            period_start=row["period_start"],
            period_end=row["period_end"],
            markdown_path=row["markdown_path"],
            html_path=row["html_path"],
            wechat_media_id=row["wechat_media_id"],
            notion_page_id=row["notion_page_id"],
            article_count=row["article_count"],
            published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
        )

    # ---- Source Health ----

    def update_source_health(self, source_id: str, success: bool, articles: int = 0, error: str | None = None) -> None:
        now = datetime.now().isoformat()
        existing = self.conn.execute(
            "SELECT * FROM source_health WHERE source_id=?", (source_id,)
        ).fetchone()

        if existing:
            if success:
                self.conn.execute(
                    """UPDATE source_health
                       SET last_success=?, articles_collected=articles_collected+?,
                           error_count=0, last_error=NULL, status='active'
                       WHERE source_id=?""",
                    (now, articles, source_id),
                )
            else:
                self.conn.execute(
                    """UPDATE source_health
                       SET last_failure=?, error_count=error_count+1,
                           last_error=?, status=CASE WHEN error_count>=3 THEN 'error' ELSE status END
                       WHERE source_id=?""",
                    (now, error or "Unknown error", source_id),
                )
        else:
            self.conn.execute(
                """INSERT INTO source_health (source_id, last_success, articles_collected, status)
                   VALUES (?, ?, ?, 'active')""",
                (source_id, now if success else None, articles),
            )
        self.conn.commit()

    def get_all_source_health(self) -> list[SourceHealth]:
        rows = self.conn.execute("SELECT * FROM source_health").fetchall()
        return [
            SourceHealth(
                source_id=r["source_id"],
                last_success=datetime.fromisoformat(r["last_success"]) if r["last_success"] else None,
                last_failure=datetime.fromisoformat(r["last_failure"]) if r["last_failure"] else None,
                error_count=r["error_count"],
                articles_collected=r["articles_collected"],
                status=r["status"],
                last_error=r["last_error"],
            )
            for r in rows
        ]

    # ---- Stats ----

    def get_category_distribution(self, issue_number: int | None = None) -> dict[str, int]:
        if issue_number is not None:
            rows = self.conn.execute(
                "SELECT category, COUNT(*) as cnt FROM articles WHERE issue_number=? AND included_in_issue=1 GROUP BY category",
                (issue_number,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT category, COUNT(*) as cnt FROM articles WHERE is_duplicate=0 GROUP BY category"
            ).fetchall()
        return {r["category"] or "uncategorized": r["cnt"] for r in rows}

    def get_total_article_count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM articles WHERE is_duplicate=0").fetchone()
        return row[0] if row else 0

    # ---- Helpers ----

    def _row_to_article(self, row: sqlite3.Row | None) -> Article | None:
        if row is None:
            return None
        return Article(
            id=row["id"],
            source_id=row["source_id"],
            source_name=row["source_name"],
            url=row["url"],
            title=row["title"],
            raw_summary=row["raw_summary"],
            content=row["content"],
            author=row["author"],
            published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
            fetched_at=datetime.fromisoformat(row["fetched_at"]) if row["fetched_at"] else datetime.now(),
            language=row["language"],
            image_url=row["image_url"],
            category=row["category"],
            summary_cn=row["summary_cn"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            entities=json.loads(row["entities"]) if row["entities"] else {},
            embedding_id=row["embedding_id"],
            cluster_id=row["cluster_id"],
            is_duplicate=bool(row["is_duplicate"]),
            duplicate_of=row["duplicate_of"],
            issue_number=row["issue_number"],
            included_in_issue=bool(row["included_in_issue"]),
        )
