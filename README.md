# hello-llm

一个最小可用的 LLM 应用骨架。Day 1 的目标只是**跑起来**。

## 能力

- `GET /` 探活
- `GET /health` 健康检查（部署用）
- `POST /chat` 普通问答
- `POST /chat/stream` 流式问答（SSE，格式对齐 OpenAI）

## 跑起来

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app:app --reload
```

打开 http://127.0.0.1:8000/docs

## 下一步

- [ ] Day 2：写 Dockerfile，打包成镜像
- [ ] Day 3：接入真实模型（vLLM 或 API），替换占位回复
