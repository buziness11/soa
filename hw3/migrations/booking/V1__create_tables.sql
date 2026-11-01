CREATE TABLE book (
    booking_id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    flight_id BIGINT NOT NULL,
    passenger_name TEXT NOT NULL,
    passenger_email TEXT NOT NULL,
    seat_count INT NOT NULL CHECK (seat_count > 0),
    total_price BIGINT NOT NULL CHECK (total_price > 0),
    status TEXT NOT NULL CHECK (status IN ('CONFIRMED', 'CANCELLED'))
);
