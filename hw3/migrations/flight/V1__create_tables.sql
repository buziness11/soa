CREATE TABLE flight (
    flight_id BIGSERIAL PRIMARY KEY,
    flight_number TEXT NOT NULL,
    airline TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin ~ '^[A-Z]{3}$'),
    destination TEXT NOT NULL CHECK (destination ~ '^[A-Z]{3}$'),
    departure_time TIMESTAMP NOT NULL,
    arrival_time TIMESTAMP NOT NULL,
    total_seats INT NOT NULL CHECK (total_seats > 0),
    available_seats INT NOT NULL CHECK (available_seats >= 0 AND available_seats <= total_seats),
    price BIGINT NOT NULL CHECK (price > 0),
    status TEXT NOT NULL CHECK (status IN ('SCHEDULED', 'DEPARTED', 'CANCELLED', 'COMPLETED')),
    CHECK (origin <> destination),
    CHECK (arrival_time > departure_time)
);

CREATE UNIQUE INDEX flight_number_date_unique
ON flight (flight_number, (departure_time::date));

CREATE TABLE seat_reserve (
    id BIGSERIAL PRIMARY KEY,
    flight_id BIGINT NOT NULL REFERENCES flight(flight_id),
    booking_id BIGINT NOT NULL UNIQUE,
    seat_count INT NOT NULL CHECK (seat_count > 0),
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RELEASED', 'EXPIRED'))
);
