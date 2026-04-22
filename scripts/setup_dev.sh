#!/usr/bin/env bash
# Полная настройка локального дев-окружения Mirror
# Запуск: bash scripts/setup_dev.sh
set -e

CYAN='\033[0;36m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${CYAN}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
die()   { echo -e "${RED}[FAIL]${NC}  $*"; exit 1; }

info "=== Mirror DEV SETUP ==="

# 1. Поднять инфраструктуру (без appsmith чтобы быстрее)
info "Поднимаю инфраструктуру (postgres, redis, qdrant, rabbitmq, nats)..."
docker compose -f docker-compose.dev.yml up -d postgres redis qdrant rabbitmq nats
sleep 5

# 2. Ждать postgres
info "Жду postgres..."
for i in $(seq 1 20); do
  docker compose -f docker-compose.dev.yml exec -T postgres pg_isready -U mirror -d mirror >/dev/null 2>&1 && break
  sleep 2
done
ok "Postgres готов"

# 3. Применить миграции
info "Применяю Alembic миграции..."
DATABASE_URL=$(grep DATABASE_URL .env | head -1 | cut -d= -f2-)
export DATABASE_URL
alembic upgrade head || die "Миграции не прошли"
ok "Миграции применены"

# 4. Применить seed
info "Применяю seed данные..."
PGHOST=localhost PGPORT=19102 PGUSER=mirror PGPASSWORD=mirror PGDATABASE=mirror \
  psql -f scripts/seed_dev.sql || warn "Seed завершился с предупреждением (возможно уже засеяно)"
ok "Seed данные применены"

# 5. Создать read-only юзера для Appsmith
info "Создаю appsmith_ro пользователя..."
PGHOST=localhost PGPORT=19102 PGUSER=mirror PGPASSWORD=mirror PGDATABASE=mirror \
  psql -f scripts/create_appsmith_ro_user.sql 2>/dev/null || warn "appsmith_ro уже существует"

# 6. Поднять Appsmith
info "Поднимаю Appsmith (UI админки)..."
docker compose -f docker-compose.dev.yml up -d appsmith

# 7. Собрать и запустить приложение
info "Собираю и запускаю mirror_api..."
docker compose -f docker-compose.dev.yml up -d --build mirror_api celery_worker celery_beat

# 8. Ждать API
info "Жду mirror_api..."
for i in $(seq 1 30); do
  curl -sf http://localhost:19100/health >/dev/null 2>&1 && break
  sleep 3
done

if curl -sf http://localhost:19100/health >/dev/null 2>&1; then
  ok "mirror_api запущен"
else
  warn "mirror_api не отвечает, проверь логи: docker compose -f docker-compose.dev.yml logs mirror_api"
fi

echo ""
echo -e "${GREEN}=== ГОТОВО ===${NC}"
echo ""
echo "  🤖  Telegram бот:    запущен в polling mode, пиши боту напрямую"
echo "  🌐  API + Swagger:   http://localhost:19100/docs"
echo "  🔑  Admin API token: admin"
echo "  📊  Appsmith UI:     http://localhost:19101  (первый запуск — регистрация)"
echo "  🐰  RabbitMQ UI:     http://localhost:19107  (guest/guest)"
echo "  🗄️   PostgreSQL:      localhost:19102 (mirror/mirror)"
echo ""
echo "  Appsmith → подключить PostgreSQL datasource:"
echo "    Host: postgres  Port: 5432  DB: mirror  User: appsmith_ro  Pass: appsmith_ro_change_me"
echo ""
echo "  Appsmith → подключить REST API datasource:"
echo "    URL: http://mirror_api:8000  Header: X-Admin-Token = admin"
echo ""
echo "  Логи бота:  docker compose -f docker-compose.dev.yml logs -f mirror_api"
