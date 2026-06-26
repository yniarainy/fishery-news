"""Extract OpenGraph image from article URLs (async, non-blocking)."""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def extract_og_image(url: str, timeout: float = 5.0) -> str | None:
    """Quickly fetch article page and extract og:image meta tag.

    Only downloads the first 64KB of HTML (enough for <head>),
    then parses for og:image or twitter:image.
    """
    try:
        client = httpx.Client(timeout=timeout, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (compatible; FisheryNewsBot/0.1)",
            "Accept": "text/html",
        })
        # Stream only first 64KB — enough for <head> and og:image
        with client.stream("GET", url) as resp:
            resp.raise_for_status()
            chunk = resp.read(65536)  # 64KB max
        html = chunk.decode("utf-8", errors="ignore")

        # Fast regex extraction (faster than BeautifulSoup for this)
        for pattern in [
            r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"',
            r"<meta[^>]+property='og:image'[^>]+content='([^']+)'",
            r'<meta[^>]+name="twitter:image"[^>]+content="([^"]+)"',
        ]:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                img_url = match.group(1)
                if img_url.startswith("/"):
                    img_url = urljoin(url, img_url)
                if img_url.startswith("http"):
                    return img_url

        # Fallback: BeautifulSoup for edge cases
        soup = BeautifulSoup(html, "lxml")
        for tag in soup.find_all("meta"):
            prop = (tag.get("property") or "").lower()
            name = (tag.get("name") or "").lower()
            content = tag.get("content", "")
            if ("og:image" in prop or "twitter:image" in name) and content:
                if content.startswith("/"):
                    content = urljoin(url, content)
                if content.startswith("http"):
                    return content

    except Exception as e:
        logger.debug(f"OG image extraction failed for {url[:60]}: {e}")

    return None


def batch_extract_images(
    urls: list[str], max_workers: int = 5, timeout: float = 3.0
) -> dict[str, str | None]:
    """Extract og:image for multiple URLs concurrently using threads."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(extract_og_image, url, timeout): url for url in urls}
        for future in as_completed(futures):
            url = futures[future]
            try:
                results[url] = future.result()
            except Exception:
                results[url] = None
    return results
