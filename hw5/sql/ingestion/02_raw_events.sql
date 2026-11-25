CREATE TABLE IF NOT EXISTS cinema.raw_events
(
    event_id UUID,
    user_id String,
    movie_id String,
    event_type LowCardinality(String),
    timestamp DateTime64(3, 'UTC'),
    device_type LowCardinality(String),
    session_id String,
    progress_seconds Nullable(UInt32)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(timestamp)
ORDER BY (toDate32(timestamp), user_id, timestamp, event_id);
