INSERT INTO flight (
    flight_number, airline, origin, destination, departure_time, arrival_time,
    total_seats, available_seats, price, status
) VALUES
    ('SU1234', 'Aeroflot', 'SVO', 'LED', '2026-12-01 10:00', '2026-12-01 11:30', 100, 100, 500000, 'SCHEDULED'),
    ('SU1234', 'Aeroflot', 'SVO', 'LED', '2026-12-02 10:00', '2026-12-02 11:30', 100, 100, 600000, 'SCHEDULED'),
    ('SU5678', 'Aeroflot', 'LED', 'SVO', '2026-12-01 14:00', '2026-12-01 15:30', 50, 50, 450000, 'SCHEDULED'),
    ('SU9999', 'Aeroflot', 'SVO', 'LED', '2026-12-01 18:00', '2026-12-01 19:30', 100, 100, 500000, 'CANCELLED');
