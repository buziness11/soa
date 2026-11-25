CREATE TABLE IF NOT EXISTS cinema.movie_queue
(
    event_id String,
    user_id String,
    movie_id String,
    event_type Enum8('VIEW_STARTED'=1, 'VIEW_FINISHED'=2, 'VIEW_PAUSED'=3,
                     'VIEW_RESUMED'=4, 'LIKED'=5, 'SEARCHED'=6),
    timestamp String,
    device_type Enum8('MOBILE'=1, 'DESKTOP'=2, 'TV'=3, 'TABLET'=4),
    session_id String,
    progress_seconds UInt32
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9092',
         kafka_topic_list = 'movie-events',
         kafka_group_name = 'cinema-clickhouse-v1',
         kafka_format = 'ProtobufSingle',
         kafka_schema = 'movie_event:MovieEvent',
         kafka_num_consumers = 1,
         kafka_flush_interval_ms = 500;
