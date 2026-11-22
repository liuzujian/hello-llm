"""配置集中管理。

原则：所有外部依赖（模型地址、密钥、超时）都从环境变量来，代码里不出现字面量。
好处：换供应商只改 .env，不动一行代码。
"""
import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()  # 读取同目录（项目根）的 .env


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str
    model: str
    timeout: float
    max_retries: int
    log_level: str


@lru_cache  # 只解析一次，避免每个请求都读环境变量
def get_settings() -> Settings:
    base_url = os.getenv("LLM_BASE_URL", "").rstrip("/")
    model = os.getenv("LLM_MODEL", "")
    if not base_url or not model:
        raise RuntimeError(
            "缺少 LLM_BASE_URL 或 LLM_MODEL。\n"
            "请把 .env.example 复制成 .env 并填好。"
        )
    return Settings(
        base_url=base_url,
        api_key=os.getenv("LLM_API_KEY", "none"),
        model=model,
        timeout=float(os.getenv("LLM_TIMEOUT", "60")),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", "2")),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
