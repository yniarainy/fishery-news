"""
统一配置加载 — 所有模块从这里获取配置，只加载一次。

优先顺序: 环境变量 > .env 文件 > settings.yaml 默认值
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG = None


def _load_env_file():
    """加载 .env 文件到 os.environ（如果存在）。"""
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        with open(env_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value


def get_config() -> dict:
    """获取全局配置（单例，自动处理模板变量和环境变量）。"""
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG

    # 1. 加载 .env
    _load_env_file()

    # 2. 读取 settings.yaml
    config_path = PROJECT_ROOT / "config" / "settings.yaml"
    with open(config_path, encoding="utf-8") as f:
        raw = f.read()

    # 3. 替换 ${VAR} 模板
    env_vars = [
        "DEEPSEEK_API_KEY", "WECHAT_APP_ID", "WECHAT_APP_SECRET",
        "NOTION_API_KEY", "NOTION_DATABASE_ID",
    ]
    for env_var in env_vars:
        raw = raw.replace(f"${{{env_var}}}", os.getenv(env_var, ""))

    _CONFIG = yaml.safe_load(raw)
    return _CONFIG


def get_sources() -> list[dict]:
    """获取已启用的信源列表。"""
    sources_path = PROJECT_ROOT / "config" / "sources.yaml"
    with open(sources_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return [s for s in data.get("sources", []) if s.get("enabled", False)]


def get_prompts() -> dict:
    """获取 LLM prompt 模板。"""
    prompts_path = PROJECT_ROOT / "config" / "prompts.yaml"
    with open(prompts_path, encoding="utf-8") as f:
        return yaml.safe_load(f)
