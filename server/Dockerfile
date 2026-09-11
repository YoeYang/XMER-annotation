FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY manage.py .

EXPOSE 8000

# 建表是幂等的；Alembic 在 P1 开跑前引入，见 deploy/README.md
CMD ["sh", "-c", "python -c 'from app.config import load_settings; from app.db import create_db_engine, create_all; create_all(create_db_engine(load_settings().database_url))' && uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000"]
