#!/usr/bin/env bash
# Первоначальное получение SSL-сертификата Let's Encrypt на сервере.
# Запускать ОДИН РАЗ после первого деплоя на прод.
# Использование: ./scripts/ssl_init.sh your@email.com admin.yourdomain.tld

set -euo pipefail
cd "$(dirname "$0")/.."

EMAIL="${1:?Укажи email: ./ssl_init.sh email domain}"
DOMAIN="${2:?Укажи домен: ./ssl_init.sh email domain}"

# Обновляем домен в nginx конфиге
sed -i "s/YOUR_DOMAIN/${DOMAIN}/g" nginx/prod.conf

# Запускаем nginx в режиме только HTTP для прохождения challenge
docker compose -f docker-compose.prod.yml up -d nginx

# Получаем сертификат
docker compose -f docker-compose.prod.yml run --rm certbot \
  certonly --webroot --webroot-path=/var/www/certbot \
  --email "$EMAIL" --agree-tos --no-eff-email \
  -d "$DOMAIN"

# Перезапускаем nginx с SSL
docker compose -f docker-compose.prod.yml restart nginx

echo "✓ SSL получен для ${DOMAIN}"
