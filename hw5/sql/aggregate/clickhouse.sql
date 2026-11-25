CREATE TABLE IF NOT EXISTS cinema.daily_metrics
(
    metric_date Date32,
    processed UInt64,
    dau UInt64,
    avg_watch_seconds Nullable(Float64),
    view_conversion Nullable(Float64),
    retention_d1 Nullable(Float64),
    retention_d7 Nullable(Float64),
    top_movies Array(Tuple(String, UInt64)),
    computed_at DateTime64(6, 'UTC')
)
ENGINE = ReplacingMergeTree(computed_at)
PARTITION BY toYYYYMM(metric_date)
ORDER BY metric_date;
