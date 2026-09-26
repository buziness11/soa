# Протокол проверки

Проверка выполнена **26 сентября 2026 года на сервере hse**, рабочая папка `~/soa/hw1`. Docker Engine 29.1.3, Linux amd64. Python хоста 3.10.12, внутри образа Python 3.13.15. Использован Dockerfile из этого репозитория.

| Проверка | Фактический результат |
|---|---|
| `python3 -m unittest discover -s services/orders -p 'test_*.py' -v` | 2 теста, OK; реальные HTTP-запросы |
| `docker build -t soa-hw1-orders:local .` | Образ успешно собран |
| `docker run … -p 127.0.0.1:18080:8080 soa-hw1-orders:local` | Контейнер запущен, состояние running |
| Встроенный Docker HEALTHCHECK | healthy |
| `GET http://127.0.0.1:18080/health` | HTTP/1.0 200 OK; `{"status":"ok","service":"orders"}` |
| GET `/orders`, `/payments`, `/missing` | 404; бизнес-эндпоинтов нет |
| Пользователь процесса | 10001:10001, не root |
| Ограничения контейнера | Файловая система read-only, cap_drop ALL |

Снимок успешной проверки: **2026-09-26T18:14:23Z**. После проверки контейнер `soa-hw1-orders` оставлен работающим для демонстрации. Это состояние на момент проверки; последующий статус смотрите через `docker inspect`.

## Сохранённые доказательства

- [Вывод HTTP-тестов](verification/python-tests.txt).
- [Вывод сборки Docker](verification/docker-build.txt).
- [Ответ curl с заголовками](verification/health-response.txt).
- [Сводка Docker inspect](verification/docker-result.json).
- [Лог контейнера](verification/container-logs.txt).

Docker Compose и buildx на hse отсутствуют. Compose-конфигурация и GitHub Actions подготовлены, но их запуск здесь **не проверен**. Обычный `docker build` завершился успешно через имеющийся builder; предупреждение Docker о его устаревании сохранено в логе. Это не ошибка сборки. Нагрузочные тесты, бизнес-сценарии и интеграции с БД/PSP не выполнялись: этих компонентов в каркасе нет.

Тег `python:3.13-slim` изменяемый; digest базового образа зафиксирован в логе сборки. Для побитовой повторяемости будущих сборок можно закрепить этот digest в Dockerfile. Для текущей проверки образ приложения имеет идентификатор из `docker-result.json`.
