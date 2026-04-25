#!/usr/bin/env bash
# Деплой на стейдж (локальная сборка для проверки)
# Использование: ./scripts/stage.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Сборка и перезапуск контейнеров..."
docker compose -f docker-compose.dev.yml up -d --build

echo "==> Ожидание готовности postgres..."
until docker compose -f docker-compose.dev.yml exec -T postgres pg_isready -U mirror -d mirror > /dev/null 2>&1; do
  sleep 1
done

echo "==> Запуск миграций Alembic..."
docker compose -f docker-compose.dev.yml exec -T mirror_api alembic upgrade head

echo ""
echo "✓ Стейдж готов: http://localhost:19100/admin/ui/"
