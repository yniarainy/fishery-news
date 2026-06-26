"""DeepSeek API client wrapper (OpenAI-compatible).

Provides both chat completion and embedding APIs through a unified interface.
Uses tenacity for automatic retry on transient failures.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

logger = logging.getLogger(__name__)


class LLMClient:
    """DeepSeek API 客户端封装。

    Usage:
        client = LLMClient(config)
        result = client.chat(system_prompt, user_prompt, response_format="json")
        embedding = client.embed("some text for vector search")
    """

    def __init__(self, config: dict):
        llm_config = config.get("llm", {})
        self.api_key = llm_config.get("api_key", "")
        self.base_url = llm_config.get("base_url", "https://api.deepseek.com")
        self.model = llm_config.get("model", "deepseek-v4-pro")
        self.embedding_model = llm_config.get("embedding_model", "deepseek-v4-flash")
        self.max_tokens = llm_config.get("max_tokens", 4096)
        self.temperature = llm_config.get("temperature", 0.3)
        self.batch_size = llm_config.get("batch_size", 10)

        self._client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        response_format: str = "text",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """调用 DeepSeek Chat API。

        Args:
            system_prompt: 系统提示
            user_prompt: 用户提示
            response_format: "text" 或 "json"
            temperature: 覆盖默认温度
            max_tokens: 覆盖默认最大 token 数

        Returns:
            LLM 响应文本
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }

        if response_format == "json":
            kwargs["response_format"] = {"type": "json_object"}

        logger.debug(f"LLM chat: model={self.model}, tokens={kwargs['max_tokens']}")
        response = self._client.chat.completions.create(**kwargs)

        content = response.choices[0].message.content or ""
        usage = response.usage
        if usage:
            logger.debug(
                f"LLM usage: prompt={usage.prompt_tokens}, "
                f"completion={usage.completion_tokens}, "
                f"total={usage.total_tokens}"
            )

        return content

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float | None = None,
    ) -> dict | list:
        """调用 LLM 并解析 JSON 响应。

        Returns:
            解析后的 dict 或 list
        """
        text = self.chat(system_prompt, user_prompt, response_format="json", temperature=temperature)

        # 尝试提取 JSON（处理 markdown code block 包裹的情况）
        text = text.strip()
        if text.startswith("```"):
            # 移除 markdown code fences
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试查找 JSON 片段
            import re
            match = re.search(r"\{.*\}|\[.*\]", text, re.DOTALL)
            if match:
                return json.loads(match.group())
            logger.warning(f"Failed to parse JSON from LLM response: {text[:200]}...")
            raise

    def embed(self, texts: str | list[str]) -> list[list[float]]:
        """生成文本的向量嵌入。

        注意: DeepSeek 目前通过 chat model 的特定用法生成嵌入，
        或使用独立的 embedding endpoint。这里先用 text-embedding 兼容方式。
        如 DeepSeek 不支持独立 embedding，则回退到用 chat model 提取特征。

        Args:
            texts: 单个文本字符串或文本列表

        Returns:
            嵌套的浮点数向量列表 [[dim1, dim2, ...], ...]
        """
        if isinstance(texts, str):
            texts = [texts]

        # 尝试使用 OpenAI 兼容的 embeddings API
        try:
            response = self._client.embeddings.create(
                model=self.embedding_model,
                input=texts,
            )
            return [d.embedding for d in response.data]
        except Exception:
            # 回退: 用 chat model 生成伪嵌入
            # 这不如真正的 embedding 模型准确，但可以跑通 MVP
            logger.warning("Embedding API not available, using chat-based fallback")
            return self._fallback_embed(texts)

    def _fallback_embed(self, texts: list[str]) -> list[list[float]]:
        """用 chat model 生成简易向量表示（MV P 回退方案）。

        实际部署时应使用 DeepSeek 的 embedding 模型或专门的嵌入服务。
        """
        embeddings = []
        for text in texts:
            prompt = (
                "Represent this fishery news article as a compact embedding for semantic search. "
                "Output exactly 128 numbers between -1 and 1, comma-separated, no other text.\n\n"
                f"Article: {text[:500]}"
            )
            try:
                result = self.chat("You are a text embedding tool. Output only numbers.", prompt)
                # 解析逗号分隔的数字
                numbers = [float(x.strip()) for x in result.split(",")[:128]]
                # 填充到 128 维
                while len(numbers) < 128:
                    numbers.append(0.0)
                embeddings.append(numbers[:128])
            except Exception:
                # 最终回退: 随机向量（去重会失效）
                import random
                logger.warning("Embedding fallback failed, using random vector. Article may not be deduped.")
                embeddings.append([random.uniform(-1, 1) for _ in range(128)])

        return embeddings

    def embed_single(self, text: str) -> list[float]:
        """生成单条文本的向量嵌入。"""
        return self.embed(text)[0]
