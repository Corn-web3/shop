FROM python:3.11-slim

WORKDIR /app

# system deps kept minimal; psycopg[binary] ships its own libpq
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

# Starts even with no keys configured; key-dependent endpoints return clear notes.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
