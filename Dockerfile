FROM python:3.12-slim

# 不写 .pyc、日志不缓冲（否则 docker logs 看不到实时输出）
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先只拷依赖清单：只要 requirements.txt 没改，这一层就命中缓存，不用重装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
        -i https://pypi.tuna.tsinghua.edu.cn/simple

# 再拷代码：改代码只会让这一层失效，上面装好的依赖仍然复用
COPY app ./app

EXPOSE 8000

# 必须监听 0.0.0.0 而不是 127.0.0.1，否则容器外部访问不到
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
