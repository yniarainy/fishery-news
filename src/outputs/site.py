"""Static HTML site generator for fishery news weekly."""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from src.storage.models import Issue

logger = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "policy": "🏛️ 政策法规",
    "science": "🔬 科学研究",
    "industry": "🏭 产业动态",
    "ngo": "🌊 NGO与环保",
    "data": "📈 数据统计",
    "other": "📋 其他",
}


def _cat_color(cat: str) -> str:
    """Return gradient colors per category for image placeholders."""
    colors = {
        "industry": "#f59e0b,#d97706",
        "policy": "#3b82f6,#1d4ed8",
        "science": "#8b5cf6,#6d28d9",
        "ngo": "#10b981,#047857",
        "data": "#ef4444,#dc2626",
    }
    return colors.get(cat, "#64748b,#475569")


def _build_category_insight(articles: list, label: str) -> dict:
    """根据该分类的文章列表，生成分类洞察（不调用 LLM，基于现有数据）。"""
    if not articles:
        return {"summary": "", "top_tags": [], "highlights": []}

    # 收集所有标签
    all_tags = []
    for a in articles:
        for t in a.get("tags", [])[:3]:
            all_tags.append(t)

    from collections import Counter
    tag_counts = Counter(all_tags)
    top_tags = [t for t, _ in tag_counts.most_common(6)]

    # 选 3 篇作为亮点（取标签最多的）
    highlights = sorted(articles, key=lambda a: len(a.get("tags", [])), reverse=True)[:3]

    summary = f"共 {len(articles)} 篇，核心话题: {'、'.join(top_tags[:4]) if top_tags else '暂无标签'}"

    return {
        "summary": summary,
        "top_tags": top_tags,
        "highlights": highlights,
    }


def _md_to_html(text: str) -> str:
    """Convert basic markdown to HTML for display: **bold**, line breaks."""
    # **bold** → <strong>bold</strong>
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Double newlines → paragraphs
    paragraphs = text.split('\n\n')
    result = []
    for p in paragraphs:
        p = p.strip()
        if p:
            # Single newlines → <br>
            p = p.replace('\n', '<br>')
            result.append(f'<p>{p}</p>')
    return '\n'.join(result)


class SiteGenerator:
    """静态 HTML 网站生成器。

    将周刊渲染为单页 HTML，支持直接部署到 GitHub Pages / Vercel。
    """

    def __init__(self, config: dict):
        output_config = config.get("output", {})
        self.site_dir = Path(output_config.get("site_dir", "site"))
        self.template_name = output_config.get("site_template", "index.html.j2")

        template_dir = Path(__file__).resolve().parent.parent.parent / "templates"
        if not template_dir.exists():
            template_dir = Path("templates")
        self.env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate(
        self,
        markdown_content: str,
        issue: Issue,
        articles: list | None = None,
        insights: dict | None = None,
        weekly_editorial: str = "",
        is_latest: bool = True,
    ) -> Path:
        """生成静态 HTML 页面。

        Args:
            markdown_content: Markdown 周刊内容（用于存档）
            issue: 周刊信息
            articles: 文章列表
            insights: AI 洞察
            weekly_editorial: 主编按语
            is_latest: 是否同时更新 index.html

        Returns:
            生成的 HTML 文件路径
        """
        self.site_dir.mkdir(parents=True, exist_ok=True)

        template = self.env.get_template(self.template_name)

        # 分类分布（兼容 RawArticle 和 DB Article）
        category_dist = {}
        if articles:
            for a in articles:
                cat = getattr(a, '_cached_category', None) or getattr(a, 'category', None) or 'other'
                category_dist[cat] = category_dist.get(cat, 0) + 1

        # 文章 dict 列表
        articles_dict = []
        if articles:
            for a in articles:
                cat = getattr(a, '_cached_category', None) or getattr(a, 'category', '') or ''
                summary = getattr(a, '_cached_summary', None) or getattr(a, 'summary_cn', '') or ''
                tags = getattr(a, '_cached_tags', None) or getattr(a, 'tags', []) or []

                img = getattr(a, 'image_url', None) or ''
                articles_dict.append({
                    "source_name": a.source_name,
                    "title": a.title,
                    "url": a.url,
                    "summary_cn": summary,
                    "category": cat,
                    "tags": tags,
                    "image_url": img,
                    "category_color": _cat_color(cat),
                })

        # 预分组：按 category 将文章分组，方便模板渲染
        cat_order = [
            ("industry", "🏭 产业动态"), ("policy", "🏛️ 政策法规"),
            ("science", "🔬 科学研究"), ("ngo", "🌊 NGO与环保"),
            ("data", "📈 数据统计"), ("other", "📋 其他"),
        ]
        grouped_articles = []
        for cat, cat_name in cat_order:
            cat_arts = [a for a in articles_dict if a["category"] == cat]
            if cat_arts:
                parts = cat_name.split(' ', 1)
                icon = parts[0] if len(parts) > 1 else ''
                label = parts[1] if len(parts) > 1 else cat_name
                # 生成该分类的洞察摘要
                insight = _build_category_insight(cat_arts, label)
                grouped_articles.append({
                    "category": cat,
                    "cat_name": cat_name,
                    "cat_icon": icon,
                    "cat_label": label,
                    "articles": cat_arts,
                    "count": len(cat_arts),
                    "insight": insight,
                })

        # 将 editorial 中的 markdown 转为 HTML
        editorial_html = _md_to_html(weekly_editorial) if weekly_editorial else ""

        ctx = {
            "issue": {
                "title": issue.title,
                "number": issue.number,
                "period_start": issue.period_start,
                "period_end": issue.period_end,
                "article_count": issue.article_count,
            },
            "grouped_articles": grouped_articles,
            "relative_root": "",  # 根页面用空路径
            "weekly_insight": insights or {},
            "weekly_editorial": editorial_html,
            "category_distribution": category_dist,
            "cat_labels": CATEGORY_LABELS,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        html = template.render(**ctx)

        # 保存到 issue 子目录 (e.g. issue-2026-W26)
        issue_dir = self.site_dir / f"issue-{issue.number}"
        issue_dir.mkdir(parents=True, exist_ok=True)
        # 子目录页面用 ../ 作为相对根路径
        ctx["relative_root"] = "../"
        html_sub = template.render(**ctx)
        issue_file = issue_dir / "index.html"
        issue_file.write_text(html_sub, encoding="utf-8")

        # 同时保存 markdown 到同目录
        md_file = issue_dir / "newsletter.md"
        md_file.write_text(markdown_content, encoding="utf-8")

        # 更新主页
        if is_latest:
            index_file = self.site_dir / "index.html"
            index_file.write_text(html, encoding="utf-8")

        # 生成简单的归档索引页
        self._generate_archive_index()

        logger.info(f"[Site] Generated: {issue_file}")
        return issue_file

    def _generate_archive_index(self) -> None:
        """生成 issue 归档列表页（带完整导航和现代设计）。"""
        issues = []
        for d in sorted(self.site_dir.glob("issue-*"), reverse=True):
            md_file = d / "newsletter.md"
            if md_file.exists():
                issue_num = d.name.replace("issue-", "")
                # 从 markdown 提取前两行作为预览
                preview = ""
                try:
                    lines = md_file.read_text(encoding="utf-8").split("\n")
                    for line in lines[1:15]:
                        stripped = line.strip()
                        if stripped and not stripped.startswith("#") and not stripped.startswith("---") and not stripped.startswith("*"):
                            preview = stripped[:120]
                            if preview:
                                break
                except Exception:
                    pass
                issues.append({
                    "number": issue_num,  # "2026-W26"
                    "path": f"{d.name}/index.html",  # 直接链接到 HTML 文件
                    "preview": preview,
                })

        archive_html = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>往期周刊 — Fishery News Weekly</title>
<style>
:root{--bg:#f0f4f8;--surface:#fff;--text:#1a202c;--text2:#64748b;--text3:#94a3b8;--border:#e2e8f0;--primary:#0ea5e9;--primary-dark:#0369a1;--primary-light:#e0f2fe;--radius:16px;--shadow:0 1px 2px rgba(0,0,0,.04),0 4px 16px rgba(0,0,0,.04);--transition:.2s}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Inter','Noto Sans SC',-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);line-height:1.7;-webkit-font-smoothing:antialiased;min-height:100vh}
.nav{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;max-width:800px;margin:0 auto}
.nav-brand{font-weight:800;font-size:1.1rem;color:var(--primary-dark);text-decoration:none;display:flex;align-items:center;gap:8px}
.nav-links{display:flex;gap:16px;align-items:center}
.nav-links a{color:var(--text2);text-decoration:none;font-size:.85rem;font-weight:500;padding:6px 12px;border-radius:8px;transition:var(--transition)}
.nav-links a:hover,.nav-links a.active{color:var(--primary);background:var(--primary-light)}
.header{text-align:center;padding:48px 20px 32px}
.header h1{font-size:2rem;font-weight:900;color:var(--primary-dark);margin-bottom:4px}
.header p{color:var(--text3);font-size:.9rem}
.issue-list{max-width:700px;margin:0 auto;padding:0 20px 40px}
.issue-item{background:var(--surface);border-radius:var(--radius);padding:20px 24px;margin-bottom:12px;box-shadow:var(--shadow);display:flex;align-items:center;gap:16px;transition:var(--transition);text-decoration:none;color:var(--text)}
.issue-item:hover{transform:translateY(-2px);box-shadow:0 4px 24px rgba(0,0,0,.08)}
.issue-num{font-size:1.5rem;font-weight:900;color:var(--primary);min-width:60px;text-align:center}
.issue-info{flex:1;min-width:0}
.issue-info .title{font-weight:600;font-size:1rem;margin-bottom:2px}
.issue-info .excerpt{font-size:.8rem;color:var(--text2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.issue-arrow{color:var(--text3);font-size:1.2rem}
.footer{text-align:center;padding:24px 20px;color:var(--text3);font-size:.82rem;border-top:1px solid var(--border)}
.footer a{color:var(--primary);text-decoration:none}
.empty{text-align:center;padding:40px;color:var(--text3)}
.empty .icon{font-size:3rem;margin-bottom:12px}
@media(max-width:640px){.issue-item{flex-direction:column;text-align:center;gap:8px}.issue-info .excerpt{white-space:normal}}
</style>
</head>
<body>
<nav class="nav">
  <a href="./" class="nav-brand"><span style="font-size:1.4rem">🐟</span>Fishery News Weekly</a>
  <div class="nav-links">
    <a href="./">最新周刊</a>
    <a href="archive.html" class="active">往期归档</a>
  </div>
</nav>
<div class="header">
  <h1>📚 往期周刊</h1>
  <p>所有已发布的渔业新闻周刊</p>
</div>
<div class="issue-list">
"""

        if not issues:
            archive_html += '<div class="empty"><div class="icon">📭</div><p>暂无往期周刊</p><p style="font-size:.8rem;margin-top:8px">首期周刊正在生成中...</p></div>'
        else:
            for iss in issues:
                archive_html += f"""<a href="{iss['path']}" class="issue-item">
  <div class="issue-num">{iss['number']}</div>
  <div class="issue-info">
    <div class="title">渔业新闻周刊 {iss['number']}</div>
    <div class="excerpt">{iss['preview'] or '点击查看完整周刊'}</div>
  </div>
  <div class="issue-arrow">→</div>
</a>
"""

        archive_html += """</div>
<footer class="footer">
  <p>🐟 Fishery News Weekly · 自动聚合全球渔业新闻</p>
  <p style="margin-top:4px"><a href="./">← 返回最新一期</a></p>
</footer>
</body>
</html>"""

        (self.site_dir / "archive.html").write_text(archive_html, encoding="utf-8")
