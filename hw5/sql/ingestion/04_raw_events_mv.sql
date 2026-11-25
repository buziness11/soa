CREATE MATERIALIZED VIEW IF NOT EXISTS cinema.raw_events_mv
TO cinema.raw_events AS
SELECT toUUID(q.event_id) AS event_id,
       q.user_id AS user_id,
       q.movie_id AS movie_id,
       toString(q.event_type) AS event_type,
       parseDateTime64BestEffort(q.timestamp, 3, 'UTC') AS timestamp,
       toString(q.device_type) AS device_type,
       q.session_id AS session_id,
       if(startsWith(toString(q.event_type), 'VIEW_'), q.progress_seconds, NULL) AS progress_seconds
FROM cinema.movie_queue AS q;
