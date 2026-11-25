-- One INSERT publishes a complete daily snapshot, including the entire top ten.
INSERT INTO cinema.daily_metrics
    (metric_date, processed, dau, avg_watch_seconds, view_conversion,
     retention_d1, retention_d7, top_movies, computed_at)
WITH
    {day:Date32} AS target_day,
    toDateTime64(target_day, 3, 'UTC') AS day_start,
    toDateTime64(target_day + 1, 3, 'UTC') AS day_end,
    day_events AS
    (
        -- A redelivery carries the same immutable event_id and payload.
        SELECT event_id, any(r.user_id) AS user_id, any(r.movie_id) AS movie_id,
               any(r.event_type) AS event_type, any(r.progress_seconds) AS progress_seconds
        FROM cinema.raw_events AS r
        WHERE r.timestamp >= day_start AND r.timestamp < day_end
        GROUP BY event_id
    ),
    totals AS
    (
        SELECT count() AS processed,
               uniqExact(user_id) AS dau,
               avgOrNullIf(progress_seconds, event_type = 'VIEW_FINISHED') AS avg_watch_seconds,
               countIf(event_type = 'VIEW_FINISHED')
                   / nullIf(countIf(event_type = 'VIEW_STARTED'), 0) AS view_conversion
        FROM day_events
    ),
    top_ten AS
    (
        SELECT movie_id, count() AS views
        FROM day_events
        WHERE event_type = 'VIEW_STARTED'
        GROUP BY movie_id
        ORDER BY views DESC, movie_id ASC
        LIMIT 10
    ),
    ranking AS
    (
        SELECT arraySort(item -> (-toInt64(item.2), item.1),
                         groupArray((movie_id, views))) AS top_movies
        FROM top_ten
    ),
    user_history AS
    (
        -- All earlier starts matter for cohort membership. Repeats do not
        -- change a user's first day or the Boolean return flags.
        SELECT user_id, min(toDate32(timestamp, 'UTC')) AS first_day,
               max(toDate32(timestamp, 'UTC') = target_day + 1) AS returned_d1,
               max(toDate32(timestamp, 'UTC') = target_day + 7) AS returned_d7
        FROM cinema.raw_events
        WHERE event_type = 'VIEW_STARTED'
          AND timestamp < toDateTime64(target_day + 8, 3, 'UTC')
        GROUP BY user_id
    ),
    cohort AS
    (
        SELECT if(target_day + 1 < {as_of:Date32},
                  sum(returned_d1) / nullIf(count(), 0), NULL) AS retention_d1,
               if(target_day + 7 < {as_of:Date32},
                  sum(returned_d7) / nullIf(count(), 0), NULL) AS retention_d7
        FROM user_history
        WHERE first_day = target_day
    )
SELECT target_day, processed, dau, avg_watch_seconds, view_conversion,
       retention_d1, retention_d7, top_movies, {computed_at:DateTime64(6, 'UTC')}
FROM totals CROSS JOIN ranking CROSS JOIN cohort
