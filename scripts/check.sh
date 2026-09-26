#!/bin/sh
# Требуются Docker с Compose v2 и curl. Запускайте из корня репозитория.
set -eu

project="marketplace-homework-check-$$"
cleanup() {
    docker compose -p "$project" down --remove-orphans
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

docker compose -p "$project" up --build --detach --wait --wait-timeout 60
response="$(curl --fail --silent --show-error "http://127.0.0.1:${PORT:-8080}/health")"
test "$response" = '{"status":"ok","service":"orders"}'
printf '%s\n' "Проверка пройдена: /health возвращает 200 OK и ожидаемый JSON."
