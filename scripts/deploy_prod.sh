#!/usr/bin/env bash
# Деплой на прод: merge new_features → main, push, SSH-деплой на сервер.
# Использование: ./scripts/deploy_prod.sh

set -euo pipefail
cd "$(dirname "$0")/.."

# ── Настройки сервера ────────────────────────────────────────────
PROD_HOST="176.57.221.9"
PROD_USER="root"
PROD_DIR="/opt/mirror"
PROD_PASS="${PROD_PASS:-}"  # передавать через env: PROD_PASS=... ./scripts/deploy_prod.sh
# ─────────────────────────────────────────────────────────────────

_ssh() {
  if [ -n "$PROD_PASS" ]; then
    sshpass -p "$PROD_PASS" ssh -o StrictHostKeyChecking=no "$@"
  else
    ssh -o StrictHostKeyChecking=no "$@"
  fi
}
_ssh_remote() {
  if [ -n "$PROD_PASS" ]; then
    sshpass -p "$PROD_PASS" ssh -o StrictHostKeyChecking=no "${PROD_USER}@${PROD_HOST}" bash -s
  else
    ssh -o StrictHostKeyChecking=no "${PROD_USER}@${PROD_HOST}" bash -s
  fi
}

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

# Проверяем что мы в new_features
if [ "$CURRENT_BRANCH" != "new_features" ]; then
  echo "ОШИБКА: деплой на прод только из ветки new_features (сейчас: $CURRENT_BRANCH)"
  exit 1
fi

# Проверяем что нет незакоммиченных изменений
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ОШИБКА: есть незакоммиченные изменения. Сначала 'комит в новые фичи'."
  exit 1
fi

echo "==> Merge new_features → main..."
git checkout main
git merge --no-ff new_features -m "release: merge new_features → main"
git push origin main

echo "==> Возврат в new_features..."
git checkout new_features

echo "==> SSH деплой на ${PROD_USER}@${PROD_HOST}:${PROD_DIR}..."
_ssh_remote <<REMOTE
  set -euo pipefail
  cd "${PROD_DIR}"

  echo "--> git pull main..."
  git pull origin main

  echo "--> docker compose build..."
  docker compose -f docker-compose.prod.yml build --pull

  echo "--> миграции..."
  docker compose -f docker-compose.prod.yml run --rm mirror_api alembic upgrade head

  echo "--> рестарт сервисов..."
  docker compose -f docker-compose.prod.yml up -d

  echo "--> статус..."
  docker compose -f docker-compose.prod.yml ps
REMOTE

echo ""
echo "✓ Прод задеплоен!"
