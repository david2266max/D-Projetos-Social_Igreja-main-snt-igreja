FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

COPY . .

ENV DATA_DIR=/app/data
ENV DB_PATH=/app/data/social_igreja_web.db
ENV UPLOAD_DIR=/app/data/uploads

RUN mkdir -p /app/data/uploads

CMD ["sh", "-c", "uvicorn web_server:app --host 0.0.0.0 --port ${PORT:-8000}"]
