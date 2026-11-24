"""LLM 客户端：把对话消息变成一个 token 流。

之所以不直接用 openai SDK，是为了让你亲手看清 SSE 协议长什么样。
看懂这个文件，以后换 vLLM / 任何 OpenAI 兼容服务都能通吃。
"""
import asyncio
import json
import logging
from typing import AsyncIterator

import httpx

from .config import get_settings

log = logging.getLogger("hello-llm.llm")

# 这些状态码属于"上游临时抽风"，等一等可能就好了
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """带状态码的可控错误，方便上层决定给用户看什么。"""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(f"[{status}] {detail}")


async def stream_chat_messages(
    messages: list[dict],
    max_tokens: int = 256,
    temperature: float = 0.3,
) -> AsyncIterator[str]:
    """核心方法：直接把 OpenAI 格式的 messages 数组透传给上游。

    上游本身就是 OpenAI 兼容协议，所以不需要把 messages 拼成一个字符串——
    拼字符串会丢掉 role 信息（system / user / assistant 的区分），
    多轮对话和 system prompt 都会失真。
    """
    s = get_settings()
    url = f"{s.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {s.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": s.model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
    }

    # 关键设计：一旦已经吐出第一个 token 就不能重试。
    # 否则用户会看到前半段重复一遍，体验直接崩。
    started = False
    last_error: Exception | None = None

    for attempt in range(s.max_retries + 1):
        try:
            timeout = httpx.Timeout(s.timeout, connect=10.0)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", "replace")[:300]
                        err = LLMError(resp.status_code, body)
                        if resp.status_code in RETRYABLE_STATUS and attempt < s.max_retries:
                            last_error = err
                            wait = 1.5 ** attempt
                            log.warning("上游返回 %s，%.1fs 后重试", resp.status_code, wait)
                            await asyncio.sleep(wait)
                            continue
                        raise err

                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            return
                        try:
                            chunk = json.loads(data)
                            delta = chunk["choices"][0]["delta"].get("content")
                        except (json.JSONDecodeError, KeyError, IndexError):
                            log.debug("跳过无法解析的行: %r", line[:120])
                            continue
                        if delta:
                            started = True
                            yield delta
                    return

        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if started:
                raise LLMError(0, "流式传输已开始，不能重试") from exc
            last_error = exc
            if attempt < s.max_retries:
                wait = 1.5 ** attempt
                log.warning("连接失败，%.1fs 后重试", wait)
                await asyncio.sleep(wait)
                continue
            raise LLMError(0, f"连不上模型服务：{exc}") from exc

        except httpx.ReadTimeout as exc:
            if started:
                raise LLMError(0, "生成过程中超时，已中断") from exc
            last_error = exc
            if attempt < s.max_retries:
                continue
            raise LLMError(0, "模型响应超时") from exc

    raise LLMError(0, f"重试次数耗尽：{last_error}")


async def stream_chat(message: str, max_tokens: int = 256) -> AsyncIterator[str]:
    """单轮简写：内部转成 messages 数组后走同一条链路。"""
    async for delta in stream_chat_messages(
        [{"role": "user", "content": message}], max_tokens
    ):
        yield delta
