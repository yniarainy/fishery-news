"""
信源自更新 Agent —— 自动发现和评估新的渔业新闻信息来源。

在每期周刊生成后运行，利用 Web 搜索发现新信源，再通过 LLM 评估可信度，
生成候选信源列表供人工审核后合并到 sources.yaml。
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


class SourceDiscoveryAgent:
    """信源发现 Agent。

    流程:
    1. 从本周聚类话题中提取搜索关键词
    2. 对每个关键词进行 web search
    3. 从搜索结果中提取新域名
    4. LLM 评估每个新域名的质量和相关性
    5. 输出候选信源到 config/sources_candidates.yaml
    """

    def __init__(self, config: dict, prompts: dict, db):
        self.config = config
        self.prompts = prompts.get("source_discovery", {})
        self.db = db

        self._llm_client = None

    @property
    def llm_client(self):
        if self._llm_client is None:
            from src.llm_client import LLMClient
            self._llm_client = LLMClient(self.config)
        return self._llm_client

    def discover(self) -> list[dict]:
        """执行信源发现。

        Returns:
            候选信源列表，格式兼容 sources.yaml
        """
        logger.info("[SourceDiscovery] Starting source discovery...")

        # 1. 获取已知域名集合
        known_domains = self._get_known_domains()

        # 2. 生成搜索查询（基于本周热门话题）
        search_queries = self._generate_search_queries()

        if not search_queries:
            logger.info("[SourceDiscovery] No search queries generated, skipping")
            return []

        # 3. 执行搜索，收集新域名
        new_sites = []
        for query in search_queries[:3]:  # 限制 3 个查询
            logger.info(f"[SourceDiscovery] Searching: {query}")
            sites = self._search_and_extract(query, known_domains)
            new_sites.extend(sites)

        if not new_sites:
            logger.info("[SourceDiscovery] No new sites found")
            return []

        # 4. LLM 评估每个新站点
        candidates = []
        for site in new_sites[:10]:  # 最多评估 10 个
            try:
                evaluation = self._evaluate_site(site)
                if evaluation.get("verdict") in ("recommend", "maybe"):
                    candidate = self._to_source_entry(site, evaluation)
                    candidates.append(candidate)
                    logger.info(
                        f"[SourceDiscovery] {evaluation['verdict']}: {site['domain']} "
                        f"(score={evaluation.get('score', '?')})"
                    )
            except Exception as e:
                logger.error(f"[SourceDiscovery] Evaluation failed for {site['domain']}: {e}")

        # 5. 保存候选信源
        if candidates:
            self._save_candidates(candidates)

        logger.info(f"[SourceDiscovery] Found {len(candidates)} candidates")
        return candidates

    def _get_known_domains(self) -> set[str]:
        """获取已知的信源域名。"""
        from urllib.parse import urlparse

        domains = set()
        sources_path = Path(self.config.get("_sources_path", "config/sources.yaml"))
        if not sources_path.exists():
            sources_path = Path("config/sources.yaml")

        try:
            with open(sources_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            for src in data.get("sources", []):
                url = src.get("url", "")
                try:
                    domain = urlparse(url).netloc.lower()
                    if domain.startswith("www."):
                        domain = domain[4:]
                    if domain:
                        domains.add(domain)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"[SourceDiscovery] Failed to load known domains: {e}")

        return domains

    def _generate_search_queries(self) -> list[str]:
        """基于近期文章生成搜索查询。"""
        queries = []

        # 从 DB 获取最近的不重复文章
        try:
            recent = self.db.get_recent_articles(days=14, exclude_duplicates=True)

            # 提取高频标签作为查询关键词
            all_tags: list[str] = []
            for article in recent[:30]:
                if article.tags:
                    all_tags.extend(article.tags)

            # 按频率排序
            from collections import Counter
            tag_counts = Counter(all_tags)
            top_tags = [tag for tag, _ in tag_counts.most_common(10)]

            # 组合渔业相关查询
            fishery_modifiers = [
                "fisheries news",
                "seafood industry",
                "aquaculture report",
                "fishery policy",
                "ocean conservation fisheries",
                "fish stock assessment",
                "fishing quota",
                "marine fisheries research",
            ]

            for tag in top_tags[:5]:
                for mod in fishery_modifiers[:2]:
                    queries.append(f"{tag} {mod}")

        except Exception as e:
            logger.warning(f"[SourceDiscovery] Failed to generate queries: {e}")

        # 始终添加通用渔业查询
        queries.extend([
            "global fisheries news 2026",
            "seafood industry report latest",
            "fisheries management policy update",
            "aquaculture innovation news",
        ])

        # 去重
        return list(dict.fromkeys(queries))[:8]

    def _search_and_extract(self, query: str, known_domains: set[str]) -> list[dict]:
        """执行 Web 搜索并提取新域名。

        使用 DuckDuckGo 或 Bing API（取决于配置）。
        """
        from urllib.parse import urlparse

        new_sites = []
        results = self._web_search(query, num_results=10)

        for result in results:
            url = result.get("url", "")
            title = result.get("title", "")
            snippet = result.get("snippet", "")

            try:
                domain = urlparse(url).netloc.lower()
                if domain.startswith("www."):
                    domain = domain[4:]
            except Exception:
                continue

            if not domain or domain in known_domains:
                continue

            # 过滤明显的非新闻源
            skip_domains = {
                "youtube.com", "facebook.com", "twitter.com", "x.com",
                "instagram.com", "linkedin.com", "reddit.com", "wikipedia.org",
                "amazon.com", "ebay.com",
            }
            if any(skip in domain for skip in skip_domains):
                continue

            known_domains.add(domain)  # 避免重复
            new_sites.append({
                "domain": domain,
                "url": url,
                "title": title,
                "snippet": snippet,
                "search_query": query,
            })

        return new_sites

    def _web_search(self, query: str, num_results: int = 10) -> list[dict]:
        """执行 Web 搜索。

        使用 DuckDuckGo HTML（免 API key），简单可靠。
        也可配置使用 Google Custom Search / Bing API。
        """
        results = []

        try:
            import httpx
            from bs4 import BeautifulSoup

            # DuckDuckGo HTML search
            url = "https://html.duckduckgo.com/html/"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = httpx.post(
                url,
                data={"q": query},
                headers=headers,
                timeout=15,
                follow_redirects=True,
            )
            resp.raise_for_status()

            soup = BeautifulSoup(resp.text, "lxml")
            for item in soup.select(".result")[:num_results]:
                title_el = item.select_one(".result__title a")
                snippet_el = item.select_one(".result__snippet")
                link_el = item.select_one(".result__url")

                title = title_el.get_text(strip=True) if title_el else ""
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""
                link = link_el.get("href", "") if link_el else ""

                # DuckDuckGo 的链接需要提取实际 URL
                if link and "uddg=" in str(link):
                    from urllib.parse import parse_qs, urlparse
                    try:
                        parsed = urlparse(link)
                        qs = parse_qs(parsed.query)
                        link = qs.get("uddg", [link])[0]
                    except Exception:
                        pass

                if title and link:
                    results.append({
                        "title": title,
                        "url": link,
                        "snippet": snippet,
                    })

        except ImportError:
            logger.warning("[SourceDiscovery] httpx/bs4 not available for web search")
        except Exception as e:
            logger.warning(f"[SourceDiscovery] Web search failed: {e}")

        return results

    def _evaluate_site(self, site: dict) -> dict:
        """用 LLM 评估网站是否适合作为渔业新闻信源。"""
        system_prompt = self.prompts.get("system", "")
        eval_prompt = self.prompts.get("evaluate", {}).get("user", "")

        user_prompt = eval_prompt.format(
            url=site.get("url", site.get("domain", "")),
            title=site.get("title", ""),
            description=site.get("snippet", ""),
            related_topics=site.get("search_query", ""),
        )

        try:
            result = self.llm_client.chat_json(system_prompt, user_prompt)
            return result if isinstance(result, dict) else {}
        except Exception as e:
            logger.error(f"[SourceDiscovery] LLM evaluation error: {e}")
            return {"score": 0, "verdict": "reject", "reasoning": f"Evaluation error: {e}"}

    def _to_source_entry(self, site: dict, evaluation: dict) -> dict:
        """将评估结果转为 sources.yaml 条目。"""
        domain = site.get("domain", "")
        url = site.get("url", f"https://{domain}")

        # 尝试推断 RSS feed URL
        rss_url = evaluation.get("rss_feed_url") or f"https://{domain}/feed"

        return {
            "id": domain.replace(".", "-"),
            "name": site.get("title", domain)[:50],
            "type": "rss",  # 默认 RSS，人工审核时可修改
            "url": rss_url,
            "category": evaluation.get("suggested_category", "industry"),
            "language": evaluation.get("suggested_language", "en"),
            "enabled": False,  # 默认禁用，需人工审核
            "description": evaluation.get("reasoning", ""),
            "_candidate_score": evaluation.get("score", 0),
            "_discovered_at": datetime.now().strftime("%Y-%m-%d"),
        }

    def _save_candidates(self, candidates: list[dict]) -> None:
        """保存候选信源到 YAML 文件。"""
        candidates_path = Path("config/sources_candidates.yaml")

        # 加载已有候选（避免重复）
        existing = []
        existing_ids = set()
        if candidates_path.exists():
            try:
                with open(candidates_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                existing = data.get("candidates", [])
                existing_ids = {c["id"] for c in existing}
            except Exception:
                pass

        # 合并去重
        for candidate in candidates:
            if candidate["id"] not in existing_ids:
                existing.append(candidate)
                existing_ids.add(candidate["id"])

        output = {
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "description": "候选信源，请人工审核后迁移到 sources.yaml 并设置 enabled: true",
            "candidates": existing,
        }

        with open(candidates_path, "w", encoding="utf-8") as f:
            yaml.dump(output, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        logger.info(
            f"[SourceDiscovery] {len(candidates)} new candidates saved to {candidates_path}"
        )
