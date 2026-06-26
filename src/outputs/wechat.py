"""WeChat Official Account (微信公众号) publisher.

Publishes newsletter as a draft to WeChat OA for manual review before sending.
Requires a verified Service Account (服务号).
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import httpx

from src.storage.models import Issue

logger = logging.getLogger(__name__)

# WeChat OA API base
WECHAT_API_BASE = "https://api.weixin.qq.com/cgi-bin"


class WeChatPublisher:
    """微信公众号发布器。

    支持:
    - 获取 access_token
    - 上传图文素材（图片转 media_id）
    - 创建草稿
    - 发布草稿（需手动确认，可选）

    参考文档: https://developers.weixin.qq.com/doc/offiaccount/Draft_Box/Add_draft.html
    """

    def __init__(self, config: dict):
        wechat_config = config.get("wechat", {})
        self.app_id = wechat_config.get("app_id", "")
        self.app_secret = wechat_config.get("app_secret", "")
        self._access_token: str | None = None
        self._token_expires: float = 0

    def get_access_token(self) -> str:
        """获取或刷新 access_token（有效期 2 小时）。"""
        if self._access_token and time.time() < self._token_expires:
            return self._access_token

        url = f"{WECHAT_API_BASE}/token"
        params = {
            "grant_type": "client_credential",
            "appid": self.app_id,
            "secret": self.app_secret,
        }

        try:
            resp = httpx.get(url, params=params, timeout=15)
            data = resp.json()

            if "access_token" in data:
                self._access_token = data["access_token"]
                self._token_expires = time.time() + data.get("expires_in", 7200) - 300
                logger.info("[WeChat] Access token refreshed")
                return self._access_token
            else:
                err_code = data.get("errcode", "unknown")
                err_msg = data.get("errmsg", "unknown error")
                raise RuntimeError(f"WeChat token error: {err_code} - {err_msg}")

        except httpx.HTTPError as e:
            raise RuntimeError(f"WeChat token HTTP error: {e}")

    def publish_draft(
        self,
        markdown_content: str,
        issue: Issue,
        articles: list | None = None,
    ) -> str:
        """创建微信公众号图文草稿。

        Args:
            markdown_content: 周刊 Markdown 内容
            issue: 周刊信息
            articles: 文章列表（可选，用于构建图文）

        Returns:
            草稿 media_id
        """
        if not self.app_id or not self.app_secret:
            raise RuntimeError("WeChat AppID/AppSecret not configured")

        token = self.get_access_token()

        # 将 Markdown 转为微信支持的 HTML
        html_content = self._markdown_to_wechat_html(markdown_content, issue)

        # 创建草稿
        url = f"{WECHAT_API_BASE}/draft/add?access_token={token}"

        draft_data = {
            "articles": [
                {
                    "title": issue.title,
                    "author": "Fishery News Weekly",
                    "digest": f"第{issue.number}期渔业新闻周刊 | {issue.period_start} ~ {issue.period_end}",
                    "content": html_content,
                    "content_source_url": "",  # 可放网站链接
                    "need_open_comment": 0,
                    "only_fans_can_comment": 0,
                }
            ]
        }

        try:
            resp = httpx.post(url, json=draft_data, timeout=30)
            data = resp.json()

            if "media_id" in data:
                media_id = data["media_id"]
                logger.info(f"[WeChat] Draft created: media_id={media_id}")
                return media_id
            else:
                err_code = data.get("errcode", "unknown")
                err_msg = data.get("errmsg", "unknown error")
                raise RuntimeError(f"WeChat draft error: {err_code} - {err_msg}")

        except httpx.HTTPError as e:
            raise RuntimeError(f"WeChat draft HTTP error: {e}")

    def _markdown_to_wechat_html(self, markdown: str, issue: Issue) -> str:
        """将 Markdown 周刊转为微信公众号兼容的 HTML。

        微信对 HTML 标签有严格限制，需要用内联样式替代 class。
        """
        # 简单的 Markdown → 微信 HTML 转换
        # 生产环境建议使用专门的转换库

        lines = markdown.split("\n")
        html_parts = [
            '<section style="padding: 10px 15px; font-size: 15px; color: #333; line-height: 1.8;">'
        ]

        in_code_block = False
        for line in lines:
            # 跳过代码块
            if line.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue

            # 标题
            if line.startswith("# ") and not line.startswith("## "):
                text = line[2:]
                html_parts.append(
                    f'<h1 style="font-size: 22px; font-weight: bold; color: #0284c7; '
                    f'text-align: center; margin: 20px 0 10px;">{text}</h1>'
                )
            elif line.startswith("## "):
                text = line[3:]
                html_parts.append(
                    f'<h2 style="font-size: 18px; font-weight: bold; color: #0ea5e9; '
                    f'margin: 15px 0 8px; border-bottom: 2px solid #e2e8f0; padding-bottom: 5px;">{text}</h2>'
                )
            elif line.startswith("### "):
                text = line[4:]
                html_parts.append(
                    f'<h3 style="font-size: 16px; font-weight: bold; color: #1e293b; '
                    f'margin: 12px 0 6px;">{text}</h3>'
                )
            # 分割线
            elif line.strip() == "---":
                html_parts.append(
                    '<hr style="border: none; border-top: 1px solid #e2e8f0; margin: 15px 0;">'
                )
            # 列表
            elif line.strip().startswith("- ") or line.strip().startswith("* "):
                text = re.sub(r"^[\s]*[-*]\s+", "", line)
                # 处理粗体
                text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
                # 处理链接
                text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2" style="color: #0ea5e9;">\1</a>', text)
                html_parts.append(f'<p style="margin: 3px 0 3px 10px;">• {text}</p>')
            # 引用
            elif line.strip().startswith("> "):
                text = line.strip()[2:]
                html_parts.append(
                    f'<blockquote style="border-left: 3px solid #0ea5e9; '
                    f'padding: 5px 10px; margin: 8px 0; background: #f0f9ff; color: #64748b;">'
                    f'{text}</blockquote>'
                )
            # 表格
            elif line.strip().startswith("|"):
                # 简化表格处理：每行作为一个段落
                cells = [c.strip() for c in line.split("|") if c.strip()]
                if all(c.startswith("---") for c in cells if c):
                    continue  # 跳过分隔行
                cell_html = " | ".join(cells)
                html_parts.append(
                    f'<p style="margin: 2px 0; font-size: 14px; color: #475569;">{cell_html}</p>'
                )
            # 加粗
            elif line.strip().startswith("**") and line.strip().endswith("**"):
                text = line.strip()[2:-2]
                html_parts.append(
                    f'<p style="font-weight: bold; margin: 8px 0;">{text}</p>'
                )
            # 普通段落
            elif line.strip():
                text = line.strip()
                text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
                text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2" style="color: #0ea5e9;">\1</a>', text)
                text = re.sub(r"`(.+?)`", r'<code style="background:#f1f5f9; padding:1px 4px; border-radius:3px;">\1</code>', text)
                html_parts.append(f'<p style="margin: 6px 0;">{text}</p>')
            # 空行
            else:
                html_parts.append("<br>")

        html_parts.append(
            f'<p style="text-align: center; color: #94a3b8; font-size: 12px; margin-top: 20px;">'
            f'自动生成 · Fishery News Weekly · 第{issue.number}期</p>'
        )
        html_parts.append("</section>")

        # 微信要求 content 长度不超过 20000 字符
        html = "\n".join(html_parts)
        if len(html) > 20000:
            logger.warning(f"[WeChat] Content too long ({len(html)} chars), truncating...")
            html = html[:19500] + '<p style="color:#94a3b8;">（内容过长，已截断）</p></section>'

        return html
