# Домашнее задание №3

## Flight Booking: gRPC + Redis
Цель задания - спроектировать и реализовать распределённую систему бронирования авиабилетов из двух микросервисов, взаимодействующих по gRPC, с кешированием в Redis.

Задание можно реализовывать на любом языке программирования и любом фреймворке.

Задание разделено на три блока по возрастанию сложности:

1-4 балла — базовая архитектура и интеграция

5-7 баллов — транзакции, аутентификация, кеширование

8-10 баллов — отказоустойчивость

Блоки оцениваются последовательно: пункты следующего блока проверяются только при полном выполнении предыдущего. Например, если из блока 1-4 выполнены только 3 пункта из 4, задания на 5-7 баллов не оцениваются.

## Архитектура системы
Система состоит из двух микросервисов с раздельными базами данных.

```text
Client (REST) → Booking Service → (gRPC) → Flight Service
                      ↓                          ↓
                 PostgreSQL               PostgreSQL + Redis
```
Booking Service - управление бронированиями. REST API для клиентов. Хранит бронирования в собственной PostgreSQL.

Flight Service - управление рейсами и местами. gRPC API для межсервисного взаимодействия. Хранит рейсы в PostgreSQL. При реализации п.7+ кеширует данные в Redis.

Каждый сервис имеет собственную БД.

## Общие требования
Все сервисы поднимаются одной командой docker-compose up.

Миграции БД применяются автоматически при старте.

.proto файлы и контракты проектируются студентом самостоятельно.

Важно: задание намеренно не содержит полной спецификации контрактов, форматов запросов/ответов и схем данных. В приложении описано поведение методов — что система должна делать. Как именно оформить .proto, REST-контракты и таблицы — решает студент. Это часть задания.

## 1-4 балла
### 1. gRPC-контракт Flight Service (1 балл)
Необходимо самостоятельно спроектировать .proto файлы для Flight Service.

Обязательные методы:

| Метод | Описание |
| --- | --- |
| `SearchFlights` | Поиск рейсов по маршруту и дате |
| `GetFlight` | Получение информации о рейсе по ID |
| `ReserveSeats` | Резервирование мест для бронирования |
| `ReleaseReservation` | Отмена резервирования (возврат мест) |

Требования:

Ключевые методы контракта отражают бизнес-операции предметной области (резервирование, поиск), а не сводятся к обёрткам над таблицами.

Используется кодогенерация из .proto (protoc).

Используются `Timestamp` для дат и enum для статусов.

Описаны стандартные gRPC error codes для бизнес-ошибок (NOT_FOUND, RESOURCE_EXHAUSTED и т.д.).

### 2. ER-диаграмма в 3NF (1 балл)
Необходимо самостоятельно спроектировать схему данных для обоих сервисов.

Система оперирует тремя основными сущностями:

Flight (Flight Service) - рейс. Содержит информацию об авиакомпании, маршруте (аэропорты вылета и прилёта в формате IATA-кодов, например VKO, LED), времени вылета и прилёта, количестве мест (общее и доступное), цене билета и статусе рейса (SCHEDULED, DEPARTED, CANCELLED, COMPLETED). Комбинация номера рейса и даты вылета уникальна (например, SU1234 на 2026-04-01 — это один конкретный рейс).

SeatReservation (Flight Service) - резервация мест на рейсе. Привязана к конкретному рейсу и бронированию из Booking Service. Хранит количество зарезервированных мест и статус резервации (ACTIVE, RELEASED, EXPIRED). Одному бронированию соответствует ровно одна резервация.

Booking (Booking Service) - бронирование. Содержит данные пассажира, ссылку на рейс из Flight Service, количество мест и стоимость. Статусы: CONFIRMED, CANCELLED.

Требования к диаграмме:

Формат: dbdiagram.io, draw.io, PlantUML, Mermaid - на выбор.

Соблюдена 3NF (3 нормальная форма).

Обеспечены ограничения целостности данных: количество доступных мест не может быть отрицательным, общее количество мест и цена - строго положительные и т.д.

### 3. PostgreSQL + реализация обоих сервисов (1 балл)
Подключёны 2 PostgreSQL (отдельная БД для каждого сервиса).

Миграции через Flyway, Liquibase или любой другой аналог.

Booking Service с реализацией эндпоинтов REST API.

Flight Service: gRPC сервер с реализацией методов из п.1.

Подробное описание методов Booking Service и Flight Service находится в приложении.

### 4. Межсервисное взаимодействие по gRPC (1 балл)
Booking Service вызывает Flight Service по gRPC при создании и отмене бронирования.

Обязательный флоу создания бронирования:

Booking Service → GetFlight - получить информацию о рейсе (в т.ч. цену).
Booking Service → ReserveSeats - зарезервировать места. ReserveSeats атомарно проверяет доступность и резервирует.
При успешном резервировании - зафиксировать цену (total_price = seat_count * flight.price) и создать запись в БД.
При ошибке - не создавать бронирование, вернуть ошибку клиенту.
Подробное описание методов Booking Service и Flight Service находится в приложении.

## 5-7 баллов
### 5. Транзакционная целостность (1 балл)
В Flight Service:

Резервирование мест: уменьшение available_seats + создание SeatReservation - в одной транзакции.

Использование SELECT FOR UPDATE для предотвращения двойного бронирования последнего места (race condition).

Отмена резервирования: возврат available_seats + обновление статуса резервации - в одной транзакции.

В Booking Service:

Создание бронирования: если gRPC-вызов ReserveSeats упал - booking не создаётся.

Нет частично применённых изменений.

### 6. Аутентификация межсервисных вызовов (1 балл)
Реализована аутентификация для gRPC-вызовов между сервисами. Выбрать один из подходов:

API Key - передача ключа в gRPC metadata.

Service JWT - токен сервиса в metadata.

Basic auth - логин/пароль в metadata.

Требования:

Flight Service проверяет аутентификацию для всех методов.

При отсутствии или невалидных credentials - gRPC error UNAUTHENTICATED.

Credentials передаются через переменные окружения контейнера.

### 7. Redis для кеширования (1 балл)
Redis используется во Flight Service для кеширования.

Что кешировать:

| Данные | Ключ (пример) | TTL |
| --- | --- | --- |
| Информация о рейсе | `flight:{id}` | 5–10 минут |
| Результаты поиска | `search:{origin}:{destination}:{date}` | 5–10 минут |

Требования:

Redis поднимается в docker-compose.

Реализована стратегия Cache-Aside (проверка кеша → при miss запрос к БД → запись в кеш с TTL).

Все ключи имеют TTL (нет бесконечного кеша).

Кеш инвалидируется при мутациях (UpdateFlight, ReserveSeats, ReleaseReservation) — после изменения данных кеш не содержит устаревших значений.

Есть логи о cache hit/miss.

## 8-10 баллов
### 8. Retry при вызовах Flight Service (1 балл)
Booking Service реализует retry для gRPC-вызовов к Flight Service.

Требования:

Максимум 3 попытки.

Exponential backoff (например: 100ms, 200ms, 400ms).

Retry только для: UNAVAILABLE, DEADLINE_EXCEEDED.

Без retry для: INVALID_ARGUMENT, NOT_FOUND, RESOURCE_EXHAUSTED.

Для мутирующих операций (ReserveSeats) обеспечена идемпотентность - повторный вызов с тем же booking_id не создаёт дубликат резервации.

### 9. Redis в кластерном режиме (1 балл)
Redis запущен в отказоустойчивой конфигурации внутри docker-compose:

Sentinel - мастер + реплика + sentinel.

Cluster - минимум 3 мастер-ноды.

Требования:

Код приложения использует клиент с поддержкой Sentinel/Cluster.

### 10. Circuit Breaker (1 балл)
Booking Service реализует паттерн Circuit Breaker для вызовов к Flight Service.

Circuit Breaker — конечный автомат с тремя состояниями:

CLOSED — штатная работа, запросы идут к Flight Service. При накоплении ошибок (например, 5 подряд или порог за окно времени) — переход в OPEN.

OPEN — все запросы к Flight Service немедленно завершаются ошибкой без реального вызова. Через заданный таймаут (например, 10-30 секунд) — переход в HALF_OPEN.

HALF_OPEN — пропускается один пробный запрос. Если успешен — переход в CLOSED. Если упал — обратно в OPEN.

Требования:

Реализован как interceptor/middleware на стороне Booking Service (не внутри бизнес-логики).

Параметры (порог ошибок, таймаут, размер окна) конфигурируются через переменные окружения.

В логах видны переходы между состояниями (CLOSED → OPEN, OPEN → HALF_OPEN, и т.д.).

В состоянии OPEN клиент получает осмысленную ошибку (например, 503 Service Unavailable), а не таймаут.

## Приложение 1. Спецификация методов
### Booking Service (REST API)
#### Поиск рейсов

```http
GET /flights?origin=SVO&destination=LED&date=2026-04-01
```

Проксирует вызов Flight Service (SearchFlights). Параметры origin и destination обязательны, date — опционален. Возвращает список рейсов со статусом SCHEDULED.

#### Получение рейса

```http
GET /flights/{id}
```

Проксирует вызов Flight Service (GetFlight). Если рейс не найден — 404.

#### Создание бронирования

```http
POST /bookings
```

Тело запроса содержит: user_id, flight_id, passenger_name, passenger_email, seat_count.

Перед созданием бронирования система обязана:

Получить информацию о рейсе - вызвать Flight Service (GetFlight). Если рейс не найден - ошибка.
Зарезервировать места - вызвать Flight Service (ReserveSeats). Если мест недостаточно - ошибка.
Зафиксировать цену - total_price = seat_count * flight.price (snapshot на момент бронирования).
Создать бронирование - записать в БД со статусом CONFIRMED.
Если резервирование не удалось - бронирование не создаётся.

#### Получение бронирования

```http
GET /bookings/{id}
```

Возвращает бронирование по ID. Если не найдено - 404.

#### Отмена бронирования

```http
POST /bookings/{id}/cancel
```

Проверить, что бронирование в статусе CONFIRMED.
Вызвать Flight Service (ReleaseReservation) - вернуть места (при решении на 3 балла можно не проверять).
Установить статус CANCELLED.
#### Список бронирований

```http
GET /bookings?user_id=X
```

Возвращает бронирования пользователя.

### Flight Service (gRPC)
Контракт проектируется студентом. Ниже - описание поведения обязательных методов.

#### SearchFlights
Поиск рейсов по маршруту (origin, destination) и опционально по дате. Возвращает список рейсов со статусом SCHEDULED.

#### GetFlight
Получение рейса по ID. Если не найден - NOT_FOUND.

#### ReserveSeats
Принимает flight_id, seat_count, booking_id. Атомарно уменьшает available_seats и создаёт SeatReservation. При недостатке мест - RESOURCE_EXHAUSTED.

#### ReleaseReservation
Принимает booking_id. Находит активную резервацию, возвращает места, ставит статус RELEASED.

## Реализация

Контракт на 1 балл: [proto/flight.proto](proto/flight.proto).

Пункт 2: [ER-диаграмма и ограничения данных](schema.md).

Установка зависимостей и генерация Python-кода из папки `hw3`:

```bash
pip install -r requirements.txt
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. proto/flight.proto
```

### Запуск сервисов (пункт 3)

```bash
docker compose up --build
```

Booking Service: `http://localhost:8080`, Flight Service (gRPC): `localhost:50051`.
Каждый сервис подключается только к своей PostgreSQL через `DATABASE_URL`.
Два контейнера Flyway автоматически применяют SQL из `migrations/booking` и `migrations/flight`
до запуска сервисов. В Flight Service добавляются четыре примера рейсов на 1–2 декабря 2026 года.
Всё время — UTC, цены — в копейках.

```bash
curl 'http://localhost:8080/flights?origin=SVO&destination=LED&date=2026-12-01'
curl 'http://localhost:8080/flights/1'

curl -X POST http://localhost:8080/bookings \
  -H 'Content-Type: application/json' \
  -d '{"user_id":1,"flight_id":1,"passenger_name":"Иван Иванов","passenger_email":"ivan@example.com","seat_count":2}'

# Подставить booking_id из ответа на POST /bookings.
curl 'http://localhost:8080/bookings/1'
curl 'http://localhost:8080/bookings?user_id=1'
curl -X POST 'http://localhost:8080/bookings/1/cancel'
```

`flight_service.py` реализует четыре метода контракта.
`booking_service.py` реализует REST API через `http.server` и вызывает Flight Service по gRPC.
Для нового бронирования сначала выделяется `booking_id` из PostgreSQL sequence,
затем вызываются `ReserveSeats` и запись в `book`. Цена берётся предварительным `GetFlight`.
Нет рейса/бронирования — HTTP 404, не хватает мест — 409, неверные параметры — 400.
Повторная отмена бронирования — 409.

Проверка REST API, gRPC и ограничений БД:

```bash
docker compose exec booking-service python -m unittest discover -s tests -v
```

Остановка: `docker compose down`. Данные сохраняются в Docker volumes.
В `ReserveSeats` строка рейса блокируется через `SELECT FOR UPDATE` до конца транзакции.

### API Key (пункт 6)

Ключ задаётся в локальном `.env` строкой `FLIGHT_API_KEY=ваш_ключ`.
Compose передаёт его обоим сервисам через переменные окружения.
`.env` исключён из Git и Docker-образа.
Booking Service отправляет ключ в metadata `x-api-key` при каждом gRPC-вызове.
Flight Service вызывает `check_api_key` из `auth.py` в начале всех четырёх методов.
Без ключа или с неверным ключом возвращается `UNAUTHENTICATED`.

### Redis (пункт 7)

Flight Service использует Redis как кеш перед PostgreSQL.
`GetFlight` кешируется под ключом `flight:{id}`, `SearchFlights` —
`search:{origin}:{destination}:{date}`. Без даты используется `all`.
Все ключи имеют TTL 300 секунд (5 минут).

При cache miss данные читаются из PostgreSQL и записываются в Redis.
При cache hit возвращается сохранённый ответ. В Redis хранятся protobuf-байты.
После успешного резервирования или возврата мест удаляются кеш рейса и все кеши поиска.
Очистка происходит после коммита PostgreSQL. Проверка мест при резервировании идёт через PostgreSQL.
Локальный `cache_lock` не даёт параллельному чтению записать старый ответ после очистки кеша.
Прямые SQL-изменения вне Flight Service автоматически кеш не очищают.

Просмотр ключей и логов:

```bash
docker compose exec redis redis-cli --scan
docker compose exec redis redis-cli TTL flight:1
docker compose logs flight-service
```

### Retry (пункт 8)

Все gRPC-вызовы Booking Service проходят через `call_flight` из `grpc_client.py`.
Максимум три попытки всего: первый вызов и два повтора с паузами 100 и 200 мс.
Повторяем только `UNAVAILABLE` и `DEADLINE_EXCEEDED`. Остальные ошибки возвращаются сразу.
Таймаут каждой попытки — 2 секунды. Повторы видны в логах Booking Service.

`booking_id` выделяется один раз до вызова `ReserveSeats` и сохраняется при повторах.
Flight Service возвращает существующую резервацию, не списывая места повторно.
Повтор с тем же ID, но другим рейсом или количеством мест — `INVALID_ARGUMENT`.
Параллельные повторы защищены уникальностью `booking_id`; после конфликта транзакция
откатывается и читается резервация, уже созданная другим запросом.
Повторный `ReleaseReservation` для RELEASED тоже успешен, места возвращаются только один раз.
Повтор HTTP-запроса `POST /bookings` — отдельное бронирование с новым ID.

Redis Sentinel/Cluster и circuit breaker пока не реализованы.
