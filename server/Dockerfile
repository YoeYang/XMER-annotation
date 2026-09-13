FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY manage.py alembic.ini ./
COPY migrations ./migrations

EXPOSE 8000

# 表结构由 Alembic 管理。create_all 不会 ALTER 已有表，有真实数据后用它改表
# 只能 drop 重建 = 数据全丢，所以启动时一律走迁移。
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000"]
