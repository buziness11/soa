# 2. Сервис в Docker — 2 балла

Python-сервис Orders содержит только `GET /health` → `200 OK`. Бизнес-логики и внешних Python-зависимостей нет.

## Запуск

Из корня репозитория, на машине с Docker:

```bash
cd 02_2_балла_Сервис
docker build -t soa-hw1-orders:local .
docker run -d --name soa-hw1-orders \
  --read-only --cap-drop ALL --security-opt no-new-privileges \
  -p 127.0.0.1:18080:8080 soa-hw1-orders:local
curl -i http://127.0.0.1:18080/health
```

Результат: `200 OK` и `{"status":"ok","service":"orders"}`.

**На hse контейнер уже работает:** после `ssh hse` можно сразу выполнить `curl`. Для повторного создания сначала удалите прежний контейнер: `docker rm -f soa-hw1-orders`.

## Проверка

```bash
docker inspect --format '{{.State.Health.Status}}' soa-hw1-orders
python3 -m unittest -v test_app.py
```

Ожидается `healthy` и два успешных теста. Healthcheck проверяет доступность HTTP-сервиса. Неизвестные пути, включая `/orders`, возвращают 404.

Фактический результат запуска: [проверка.txt](проверка.txt).

При установленном Compose можно использовать `PORT=18082 docker compose up --build --wait`; для остановки — `docker compose down`. `check.sh` и GitHub Actions проверяют этот вариант автоматически; их запуск на hse не выполнялся, поскольку Compose там отсутствует.
