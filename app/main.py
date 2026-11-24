"""HTTP 层：两套接口并存。

1. 自有接口    /chat、/chat/stream               —— 简单，自己用
2. OpenAI 兼容 /v1/chat/completions、/v1/models  —— 标准，任何客户端都能接

第二套是"能被别人的系统调用"的关键：Open WebUI、LobeChat、Dify、
以及各种官方 SDK 都只认这个协议。
"""
import json
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import get_settings
from .llm import LLMError, stream_chat, stream_chat_messages

settings = get_settings()
logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("hello-llm")

app = FastAPI(title="hello-llm", version="0.3.0")


# ============================================================
# 一、自有接口
# ============================================================
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


# ============================================================
# 二、OpenAI 兼容层
# ============================================================
class OAIMessage(BaseModel):
    role: str
    content: str = ""


class OAIRequest(BaseModel):
    model: str = ""
    messages: list[OAIMessage]
    max_tokens: int | None = None
    temperature: float | None = None
    stream: bool = False


def _sse(obj: dict) -> str:
    """按 OpenAI 的格式封一个 SSE 事件。"""
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@app.get("/v1/models")
def list_models():
    """客户端启动时会先问"你有哪些模型"，没有这个接口连不上。"""
    return {
        "object": "list",
        "data": [
            {
                "id": settings.model,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "hello-llm",
            }
        ],
    }


@app.post("/v1/chat/completions")
async def openai_chat_completions(body: OAIRequest):
    """OpenAI 标准对话接口。

    注意 model 字段的处理：客户端传什么都原样回显，但真正请求上游时
    永远用 .env 里配的那个模型 —— 否则客户端随便填一个就会报模型不存在。
    """
    if not body.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")

    messages = [m.model_dump() for m in body.messages]
    model_name = body.model or settings.model
    max_tokens = body.max_tokens or 256
    temperature = body.temperature if body.temperature is not None else 0.3
    cid = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())

    # ---- 非流式 ----
    if not body.stream:
        parts: list[str] = []
        try:
            async for delta in stream_chat_messages(messages, max_tokens, temperature):
                parts.append(delta)
        except LLMError as exc:
            log.error("openai 非流式失败: %s", exc)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {
            "id": cid,
            "object": "chat.completion",
            "created": created,
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "".join(parts)},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    # ---- 流式 ----
    def chunk(delta: dict, finish: str | None = None) -> str:
        return _sse(
            {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model_name,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
        )

    async def gen():
        # 第一个块只带角色，这是 OpenAI 的标准行为，部分客户端依赖它
        yield chunk({"role": "assistant"})
        try:
            async for delta in stream_chat_messages(messages, max_tokens, temperature):
                yield chunk({"content": delta})
            yield chunk({}, finish="stop")
            yield "data: [DONE]\n\n"
        except LLMError as exc:
            log.error("openai 流式失败: %s", exc)
            yield _sse({"error": {"message": str(exc), "type": "upstream_error"}})
            yield "data: [DONE]\n\n"
        except Exception:
            log.exception("openai 流式未知错误")
            yield _sse({"error": {"message": "服务内部错误", "type": "internal_error"}})
            yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
