"""HTTP 层：只负责"收请求、抛给 llm、把结果吐回去"。

分层的好处：以后加 RAG，只需要在这里插一个检索步骤，llm.py 完全不用动。
"""
import json
import logging

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .llm import LLMError, stream_chat

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("hello-llm")

app = FastAPI(title="hello-llm", version="0.2.0")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    max_tokens: int = Field(256, ge=1, le=2048)


@app.get("/")
def root():
    return {"service": "hello-llm", "version": app.version}


@app.get("/health")
def health():
    return {"ok": True, "model": settings.model, "upstream": settings.base_url}


@app.post("/chat")
async def chat(req: ChatRequest):
    """非流式：内部拼完再一次性返回。适合脚本调用。"""
    parts: list[str] = []
    try:
        async for delta in stream_chat(req.message, req.max_tokens):
            parts.append(delta)
    except LLMError as exc:
        log.error("chat 失败: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"reply": "".join(parts)}


@app.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    """流式：边生成边吐，前端一个字一个字显示。"""

    async def gen():
        try:
            async for delta in stream_chat(req.message, req.max_tokens):
                chunk = {"choices": [{"delta": {"content": delta}}]}
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except LLMError as exc:
            log.error("流式失败: %s", exc)
            payload = {"error": str(exc)}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception:
            log.exception("流式未知错误")
            payload = {"error": "服务内部错误"}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
