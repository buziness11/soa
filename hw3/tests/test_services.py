import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

import grpc
import psycopg
import redis

from proto import flight_pb2, flight_pb2_grpc
from grpc_client import call_flight


API_URL = 'http://localhost:8080'
BOOKING_DATABASE_URL = os.environ['DATABASE_URL']
FLIGHT_DATABASE_URL = 'postgresql://flight:flight@flight-db:5432/flight'


class LostResponse(grpc.RpcError):
    def code(self):
        return grpc.StatusCode.UNAVAILABLE


class DropFirstResponse:
    def __init__(self, method):
        self.method = method
        self.calls = 0

    def __call__(self, request, metadata, timeout):
        response = self.method(request, metadata=metadata, timeout=timeout)
        self.calls += 1
        if self.calls == 1:
            raise LostResponse()
        return response


class ServicesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.channel = grpc.insecure_channel(os.environ['FLIGHT_SERVICE_ADDR'])
        cls.stub = flight_pb2_grpc.FlightServiceStub(cls.channel)
        cls.metadata = (('x-api-key', os.environ['FLIGHT_API_KEY']),)
        cls.redis = redis.Redis.from_url('redis://redis:6379/0')

    @classmethod
    def tearDownClass(cls):
        cls.channel.close()

    def setUp(self):
        self.flight_number = 'TEST' + uuid4().hex[:8]
        with psycopg.connect(FLIGHT_DATABASE_URL) as conn:
            row = conn.execute(
                'INSERT INTO flight (flight_number, airline, origin, destination, departure_time, arrival_time, '
                'total_seats, available_seats, price, status) '
                "VALUES (%s, 'Test', 'DME', 'KZN', '2026-12-03 10:00', '2026-12-03 12:00', 3, 3, 10000, 'SCHEDULED') "
                'RETURNING flight_id', (self.flight_number,),
            ).fetchone()
        self.flight_id = row[0]
        self.user_id = self.flight_id + 1000000
        self.clear_cache()

    def tearDown(self):
        with psycopg.connect(BOOKING_DATABASE_URL) as conn:
            conn.execute('DELETE FROM book WHERE user_id = %s', (self.user_id,))
        with psycopg.connect(FLIGHT_DATABASE_URL) as conn:
            conn.execute('DELETE FROM seat_reserve WHERE flight_id = %s', (self.flight_id,))
            conn.execute('DELETE FROM flight WHERE flight_id = %s', (self.flight_id,))
        self.clear_cache()

    def clear_cache(self):
        self.redis.delete(f'flight:{self.flight_id}')
        for key in self.redis.scan_iter(match='search:DME:KZN:*'):
            self.redis.delete(key)

    def http(self, method, path, body=None):
        data = None
        if body is not None:
            data = json.dumps(body).encode()
        request = Request(API_URL + path, data=data, method=method,
                          headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)

    def booking_body(self, count=2):
        return {
            'user_id': self.user_id, 'flight_id': self.flight_id,
            'passenger_name': 'Иван Иванов', 'passenger_email': 'ivan@example.com',
            'seat_count': count,
        }

    def get_flight(self):
        return self.stub.GetFlight(flight_pb2.GetFlightRequest(flight_id=self.flight_id), metadata=self.metadata, timeout=5)

    def test_search_and_get(self):
        status, flights = self.http('GET', '/flights?origin=DME&destination=KZN&date=2026-12-03')
        self.assertEqual(status, 200)
        self.assertIn(self.flight_id, [flight['flight_id'] for flight in flights])
        status, flights = self.http('GET', '/flights?origin=DME&destination=KZN&date=2026-12-04')
        self.assertEqual(flights, [])
        status, flights = self.http('GET', '/flights?origin=DME&destination=KZN')
        self.assertIn(self.flight_id, [flight['flight_id'] for flight in flights])
        status, flight = self.http('GET', '/flights/' + str(self.flight_id))
        self.assertEqual(flight['departure_time'], '2026-12-03T10:00:00Z')
        self.assertEqual(flight['price'], 10000)
        with psycopg.connect(FLIGHT_DATABASE_URL) as conn:
            conn.execute("UPDATE flight SET status = 'CANCELLED' WHERE flight_id = %s", (self.flight_id,))
        self.clear_cache()
        status, flights = self.http('GET', '/flights?origin=DME&destination=KZN')
        self.assertNotIn(self.flight_id, [flight['flight_id'] for flight in flights])

    def test_grpc_reserve_and_release(self):
        booking_id = self.flight_id + 1000000000
        reservation = self.stub.ReserveSeats(flight_pb2.ReserveSeatsRequest(
            flight_id=self.flight_id, booking_id=booking_id, seat_count=2,
        ), metadata=self.metadata, timeout=5)
        self.assertEqual(reservation.status, flight_pb2.ACTIVE)
        self.assertEqual(self.get_flight().available_seats, 1)
        self.stub.ReleaseReservation(flight_pb2.ReleaseReservationRequest(booking_id=booking_id), metadata=self.metadata, timeout=5)
        self.assertEqual(self.get_flight().available_seats, 3)
        with psycopg.connect(FLIGHT_DATABASE_URL) as conn:
            row = conn.execute('SELECT status FROM seat_reserve WHERE booking_id = %s', (booking_id,)).fetchone()
        self.assertEqual(row[0], 'RELEASED')
        self.stub.ReleaseReservation(flight_pb2.ReleaseReservationRequest(booking_id=booking_id), metadata=self.metadata, timeout=5)
        self.assertEqual(self.get_flight().available_seats, 3)

    def test_reservation_idempotency(self):
        booking_id = self.flight_id + 1000000000
        request = flight_pb2.ReserveSeatsRequest(flight_id=self.flight_id, booking_id=booking_id, seat_count=2)
        first = self.stub.ReserveSeats(request, metadata=self.metadata, timeout=5)
        second = self.stub.ReserveSeats(request, metadata=self.metadata, timeout=5)
        self.assertEqual(first, second)
        self.assertEqual(self.get_flight().available_seats, 1)
        with psycopg.connect(FLIGHT_DATABASE_URL) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM seat_reserve WHERE booking_id = %s', (booking_id,)).fetchone()[0], 1)
        with self.assertRaises(grpc.RpcError) as error:
            self.stub.ReserveSeats(flight_pb2.ReserveSeatsRequest(
                flight_id=self.flight_id, booking_id=booking_id, seat_count=1,
            ), metadata=self.metadata, timeout=5)
        self.assertEqual(error.exception.code(), grpc.StatusCode.INVALID_ARGUMENT)
        self.stub.ReleaseReservation(flight_pb2.ReleaseReservationRequest(booking_id=booking_id), metadata=self.metadata, timeout=5)
        released = self.stub.ReserveSeats(request, metadata=self.metadata, timeout=5)
        self.assertEqual(released.status, flight_pb2.RELEASED)
        self.assertEqual(self.get_flight().available_seats, 3)

    def test_parallel_reservation_idempotency(self):
        booking_id = self.flight_id + 1000000000
        request = flight_pb2.ReserveSeatsRequest(flight_id=self.flight_id, booking_id=booking_id, seat_count=2)
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = []
            for i in range(4):
                futures.append(pool.submit(self.stub.ReserveSeats, request, metadata=self.metadata, timeout=5))
            reservations = [future.result() for future in futures]
        self.assertTrue(all(reservation == reservations[0] for reservation in reservations))
        self.assertEqual(self.get_flight().available_seats, 1)
        with psycopg.connect(FLIGHT_DATABASE_URL) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM seat_reserve WHERE booking_id = %s', (booking_id,)).fetchone()[0], 1)

    def test_retry_after_lost_response(self):
        booking_id = self.flight_id + 1000000000
        reserve = DropFirstResponse(self.stub.ReserveSeats)
        call_flight(reserve, flight_pb2.ReserveSeatsRequest(
            flight_id=self.flight_id, booking_id=booking_id, seat_count=2,
        ), self.metadata)
        self.assertEqual(reserve.calls, 2)
        self.assertEqual(self.get_flight().available_seats, 1)
        with psycopg.connect(FLIGHT_DATABASE_URL) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM seat_reserve WHERE booking_id = %s', (booking_id,)).fetchone()[0], 1)
        release = DropFirstResponse(self.stub.ReleaseReservation)
        call_flight(release, flight_pb2.ReleaseReservationRequest(booking_id=booking_id), self.metadata)
        self.assertEqual(release.calls, 2)
        self.assertEqual(self.get_flight().available_seats, 3)

    def test_booking_lifecycle(self):
        status, booking = self.http('POST', '/bookings', self.booking_body())
        self.assertEqual(status, 201)
        self.assertEqual(booking['total_price'], 20000)
        self.assertEqual(booking['status'], 'CONFIRMED')
        self.assertEqual(self.get_flight().available_seats, 1)
        booking_id = booking['booking_id']
        with psycopg.connect(FLIGHT_DATABASE_URL) as conn:
            conn.execute('UPDATE flight SET price = 15000 WHERE flight_id = %s', (self.flight_id,))
        status, saved = self.http('GET', '/bookings/' + str(booking_id))
        self.assertEqual(saved, booking)
        status, bookings = self.http('GET', '/bookings?user_id=' + str(self.user_id))
        self.assertEqual(bookings, [booking])
        status, cancelled = self.http('POST', '/bookings/' + str(booking_id) + '/cancel')
        self.assertEqual(status, 200)
        self.assertEqual(cancelled['status'], 'CANCELLED')
        self.assertEqual(self.get_flight().available_seats, 3)
        status, _ = self.http('POST', '/bookings/' + str(booking_id) + '/cancel')
        self.assertEqual(status, 409)

    def test_failed_booking_creates_nothing(self):
        status, _ = self.http('POST', '/bookings', self.booking_body(count=4))
        self.assertEqual(status, 409)
        status, _ = self.http('POST', '/bookings', self.booking_body(count=0))
        self.assertEqual(status, 400)
        body = self.booking_body()
        body['flight_id'] = -1
        status, _ = self.http('POST', '/bookings', body)
        self.assertEqual(status, 404)
        status, bookings = self.http('GET', '/bookings?user_id=' + str(self.user_id))
        self.assertEqual(bookings, [])
        self.assertEqual(self.get_flight().available_seats, 3)
        with psycopg.connect(FLIGHT_DATABASE_URL) as conn:
            count = conn.execute('SELECT count(*) FROM seat_reserve WHERE flight_id = %s', (self.flight_id,)).fetchone()[0]
        self.assertEqual(count, 0)

    def test_required_errors(self):
        with self.assertRaises(grpc.RpcError) as error:
            self.stub.ReleaseReservation(flight_pb2.ReleaseReservationRequest(booking_id=-1), metadata=self.metadata, timeout=5)
        self.assertEqual(error.exception.code(), grpc.StatusCode.NOT_FOUND)
        for path in ['/flights/-1', '/bookings/-1']:
            status, _ = self.http('GET', path)
            self.assertEqual(status, 404)
        for path in ['/flights', '/flights?origin=BADCODE&destination=LED', '/flights?origin=SVO&destination=LED&date=bad']:
            status, _ = self.http('GET', path)
            self.assertEqual(status, 400)
        for count, code in [(0, grpc.StatusCode.INVALID_ARGUMENT), (4, grpc.StatusCode.RESOURCE_EXHAUSTED)]:
            with self.assertRaises(grpc.RpcError) as error:
                self.stub.ReserveSeats(flight_pb2.ReserveSeatsRequest(
                    flight_id=self.flight_id, seat_count=count, booking_id=self.flight_id + 1000000000,
                ), metadata=self.metadata, timeout=5)
            self.assertEqual(error.exception.code(), code)

    def test_grpc_authentication(self):
        booking_id = self.flight_id + 1000000000
        calls = [
            (self.stub.SearchFlights, flight_pb2.SearchFlightsRequest(origin='DME', destination='KZN')),
            (self.stub.GetFlight, flight_pb2.GetFlightRequest(flight_id=self.flight_id)),
            (self.stub.ReserveSeats, flight_pb2.ReserveSeatsRequest(flight_id=self.flight_id, booking_id=booking_id, seat_count=1)),
            (self.stub.ReleaseReservation, flight_pb2.ReleaseReservationRequest(booking_id=booking_id)),
        ]
        self.get_flight()
        self.stub.SearchFlights(calls[0][1], metadata=self.metadata, timeout=5)
        for method, request in calls:
            for metadata in [(), (('x-api-key', 'wrong-key'),), (('x-api-key', ''),)]:
                with self.assertRaises(grpc.RpcError) as error:
                    method(request, metadata=metadata, timeout=5)
                self.assertEqual(error.exception.code(), grpc.StatusCode.UNAUTHENTICATED)
        self.assertEqual(self.get_flight().available_seats, 3)
        with psycopg.connect(FLIGHT_DATABASE_URL) as conn:
            count = conn.execute('SELECT count(*) FROM seat_reserve WHERE flight_id = %s', (self.flight_id,)).fetchone()[0]
        self.assertEqual(count, 0)

    def test_flight_cache_and_ttl(self):
        key = f'flight:{self.flight_id}'
        self.assertFalse(self.redis.exists(key))
        first = self.get_flight()
        cached = flight_pb2.Flight.FromString(self.redis.get(key))
        self.assertEqual(cached, first)
        self.assertGreater(self.redis.ttl(key), 0)
        self.assertLessEqual(self.redis.ttl(key), 300)
        hits = self.redis.info('stats')['keyspace_hits']
        self.assertEqual(self.get_flight(), first)
        self.assertGreater(self.redis.info('stats')['keyspace_hits'], hits)
        self.redis.expire(key, 0)
        self.assertEqual(self.get_flight(), first)
        self.assertGreater(self.redis.ttl(key), 0)

    def test_search_cache(self):
        for date in ['2026-12-03', '2026-12-04', 'all']:
            path = '/flights?origin=DME&destination=KZN'
            if date != 'all':
                path += '&date=' + date
            status, first = self.http('GET', path)
            self.assertEqual(status, 200)
            key = 'search:DME:KZN:' + date
            self.assertTrue(self.redis.exists(key))
            self.assertGreater(self.redis.ttl(key), 0)
            self.assertLessEqual(self.redis.ttl(key), 300)
            hits = self.redis.info('stats')['keyspace_hits']
            status, second = self.http('GET', path)
            self.assertEqual(second, first)
            self.assertGreater(self.redis.info('stats')['keyspace_hits'], hits)
            if date == '2026-12-04':
                self.assertEqual(second, [])

    def test_cache_invalidation(self):
        flight_key = f'flight:{self.flight_id}'
        search_key = 'search:DME:KZN:2026-12-03'
        all_dates_key = 'search:DME:KZN:all'
        search_path = '/flights?origin=DME&destination=KZN&date=2026-12-03'
        self.get_flight()
        self.http('GET', search_path)
        self.http('GET', '/flights?origin=DME&destination=KZN')
        self.assertEqual(self.redis.exists(flight_key, search_key, all_dates_key), 3)

        status, booking = self.http('POST', '/bookings', self.booking_body())
        self.assertEqual(status, 201)
        self.assertEqual(self.redis.exists(flight_key, search_key, all_dates_key), 0)
        self.assertEqual(self.get_flight().available_seats, 1)
        status, flights = self.http('GET', search_path)
        self.assertEqual(flights[0]['available_seats'], 1)

        status, _ = self.http('POST', '/bookings/' + str(booking['booking_id']) + '/cancel')
        self.assertEqual(status, 200)
        self.assertEqual(self.redis.exists(flight_key, search_key), 0)
        self.assertEqual(self.get_flight().available_seats, 3)
        status, flights = self.http('GET', search_path)
        self.assertEqual(flights[0]['available_seats'], 3)

    def test_database_constraints(self):
        for sql in ['UPDATE flight SET available_seats = -1 WHERE flight_id = %s',
                    'UPDATE flight SET available_seats = 4 WHERE flight_id = %s',
                    'UPDATE flight SET price = 0 WHERE flight_id = %s']:
            with self.assertRaises(psycopg.errors.CheckViolation):
                with psycopg.connect(FLIGHT_DATABASE_URL) as conn:
                    conn.execute(sql, (self.flight_id,))
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with psycopg.connect(FLIGHT_DATABASE_URL) as conn:
                conn.execute(
                    'INSERT INTO flight (flight_number, airline, origin, destination, departure_time, arrival_time, '
                    'total_seats, available_seats, price, status) '
                    "VALUES (%s, 'Test', 'DME', 'KZN', '2026-12-03 15:00', '2026-12-03 17:00', 3, 3, 10000, 'SCHEDULED')",
                    (self.flight_number,),
                )

    def test_database_separation_and_migrations(self):
        for database_url, expected, versions in [
            (BOOKING_DATABASE_URL, ['book'], ['1']),
            (FLIGHT_DATABASE_URL, ['flight', 'seat_reserve'], ['1', '2']),
        ]:
            with psycopg.connect(database_url) as conn:
                rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'flyway_schema_history' ORDER BY tablename").fetchall()
                self.assertEqual([row[0] for row in rows], expected)
                rows = conn.execute('SELECT version FROM flyway_schema_history WHERE success ORDER BY installed_rank').fetchall()
                self.assertEqual([row[0] for row in rows], versions)


if __name__ == '__main__':
    unittest.main()
