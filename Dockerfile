FROM python:3.12-slim

WORKDIR /app

# Системные зависимости (geopy, kerykeion, asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Зависимости Python
COPY pyproject.toml ./
RUN pip install --no-cache-dir poetry==1.8.4 \
    && poetry config virtualenvs.create false \
    && poetry install --no-root --no-interaction

# Код приложения
COPY mirror/ ./mirror/

EXPOSE 8000

CMD ["uvicorn", "mirror.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
