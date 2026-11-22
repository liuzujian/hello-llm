# hello-llm

一个可运行的大模型对话服务骨架：**OpenAI 兼容协议 + SSE 流式输出 + 配置外置 + 分层结构**。

不是 demo 截图工程——clone 下来配一个模型地址就能跑，可作为 RAG / Agent 类应用的起点。

---

## 特性

| 能力 | 说明 |
|---|---|
| 流式输出 | SSE 协议，格式对齐 OpenAI，前端可逐字渲染 |
| 供应商无关 | 只依赖 `base_url + api_key + model`，DeepSeek / 硅基流动 / Ollama / vLLM 通用 |
| 错误处理 | 上游 401/429/5xx 分类处理，可重试状态自动退避重试 |
| 配置外置 | 所有密钥与地址走环境变量，代码零硬编码 |
| 分层结构 | 配置 / 模型客户端 / HTTP 层解耦，加 RAG 时不动传输层 |

---

## 快速开始

### 1. 准备环境

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

### 2. 配置模型

```powershell
Copy-Item .env.example .env
```

打开 `.env`，**只取消一组**注释并填值（三组同时生效会以后出现的为准，这是最常见的坑）：

```ini
# DeepSeek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-xxxxxxxx
LLM_MODEL=deepseek-chat
```

<details>
<summary>其他供应商的填法</summary>

```ini
# 硅基流动
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_MODEL=Qwen/Qwen2.5-7B-Instruct

# 本地 Ollama（无需 key）
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=qwen2.5:1.5b

# 自己起的 vLLM
LLM_BASE_URL=http://127.0.0.1:8000/v1
LLM_API_KEY=EMPTY
LLM_MODEL=Qwen3-4B-Instruct
```
</details>

### 3. 启动

```powershell
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

> 改 `.env` 后必须重启——`--reload` 只监视 `.py` 文件，不监视 `.env`。

### 4. 验证

打开 <http://127.0.0.1:8000/docs>，或命令行：

```powershell
curl.exe -N -X POST http://127.0.0.1:8000/chat/stream `
  -H "Content-Type: application/json" `
  -d '{\"message\":\"用一句话解释什么是向量数据库\"}'
```

应当收到逐条 `data: {"choices":[{"delta":{"content":"..."}}]}`，以 `data: [DONE]` 结束。

---

## Docker 部署

```powershell
docker build -t hello-llm:v2 .
docker run --rm -p 8000:8000 --env-file .env hello-llm:v2
```

配置通过 `--env-file` 注入，镜像内不含任何密钥（`.dockerignore` 已排除 `.env`）。

构建的三个要点：

| 做法 | 原因 |
|---|---|
| `COPY requirements.txt` 放在 `COPY app` 之前 | 依赖未变时命中层缓存，改代码只需几秒重建（第二次构建可见 `CACHED`） |
| `ENV PYTHONUNBUFFERED=1` | 否则 stdout 被缓冲，`docker logs` 看不到实时日志 |
| `--host 0.0.0.0` | 写 `127.0.0.1` 会导致容器外部无法访问 |

> 若基础镜像拉取失败（`auth.docker.io` 超时），需为 Docker 配置代理或使用国内镜像地址。

---

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 服务信息 |
| GET | `/health` | 健康检查，返回当前模型与上游地址 |
| POST | `/chat` | 非流式，内部聚合后返回完整答案 |
| POST | `/chat/stream` | 流式（SSE），逐 token 返回 |

请求体：

```json
{ "message": "你好", "max_tokens": 256 }
```

---

## 项目结构

```
hello-llm/
├── app/
│   ├── config.py      # 环境变量 → 不可变 Settings 对象，带启动期校验
│   ├── llm.py         # 上游模型客户端：SSE 解析、超时、重试、错误分类
│   └── main.py        # HTTP 层：路由、参数校验、错误 → 状态码映射
├── Dockerfile
├── .env.example       # 配置模板（三组供应商，默认全部注释）
└── requirements.txt
```

---

## 关键设计

**1. 配置外置，代码零硬编码**
`config.py` 用 `@lru_cache` 只解析一次环境变量，缺字段在**启动期**就抛错，而不是等第一个请求才 500。换供应商只改 `.env`。

**2. 流式一旦开始就不能重试**
`llm.py` 里的 `started` 标志位：只在**首个 token 之前**允许重试连接或重试 5xx。一旦已吐出内容，任何重试都会让用户看到重复的前半段。这是流式接口最容易忽略的坑。

**3. 上游故障不能拖垮本服务**
上游 401/429/超时均被捕获并转换为可读错误，通过流返回给调用方，HTTP 状态码保持 200。前端拿到的是结构化的 `{"error": "..."}`，而不是连接中断。

**4. 分层服务于后续迭代**
加 RAG 时只需在 `main.py` 的请求流程里插入检索步骤，`llm.py` 的传输逻辑完全不用动。

---

## 已知限制

- 无鉴权，仅适合本机或内网使用
- 无多轮会话记忆（每次请求独立）
- 无请求限流与并发保护
- 无单元测试

---

## Roadmap

- [x] 接入真实模型 + SSE 流式
- [x] 分层重构与配置外置
- [x] 上游错误分类与重试
- [x] Docker 打包与运行验证（镜像内流式对话已验证）
- [ ] 文档解析 + 向量检索（RAG）
- [ ] 评测集与准确率指标
- [ ] 请求日志与反馈收集
