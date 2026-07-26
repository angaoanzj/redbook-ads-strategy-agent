FROM python:3.13-slim

# 避免写入 .pyc 并让日志实时输出
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 先只拷贝依赖清单并安装，利用 Docker 层缓存：
# 只要 requirements.txt 不变，重建镜像时无需重新安装依赖。
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 再拷贝项目全部文件（web/examples/docs/tests 等都包含在内）
COPY . .

# 创建非 root 用户运行，并确保数据目录可写
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8010

# 生产/演示启动：不启用 reload
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8010"]
