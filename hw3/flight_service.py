import os
import re
from concurrent import futures
from datetime import time, timedelta

import grpc
from google.protobuf.empty_pb2 import Empty
from psycopg.errors import SerializationFailure, UniqueViolation

from auth import check_api_key
from cache import cache_lock, get_cached, invalidate, set_cached
from db import connect
from proto import flight_pb2, flight_pb2_grpc


def flight_message(row):
    flight = flight_pb2.Flight(
        flight_id=row['flight_id'],
        flight_number=row['flight_number'],
        airline=row['airline'],
        origin=row['origin'],
        destination=row['destination'],
        total_seats=row['total_seats'],
        available_seats=row['available_seats'],
        price=row['price'],
        status=row['status'],
    )
    flight.departure_time.FromDatetime(row['departure_time'])
    flight.arrival_time.FromDatetime(row['arrival_time'])
    return flight


def reservation_message(row):
    return flight_pb2.SeatReservation(
        id=row['id'], flight_id=row['flight_id'], booking_id=row['booking_id'],
        seat_count=row['seat_count'], status=row['status'],
    )


class FlightService(flight_pb2_grpc.FlightServiceServicer):
    def SearchFlights(self, request, context):
        check_api_key(context)
        if not re.fullmatch('[A-Z]{3}', request.origin) or not re.fullmatch('[A-Z]{3}', request.destination):
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid airport code')

        sql = "SELECT * FROM flight WHERE origin = %s AND destination = %s AND status = 'SCHEDULED'"
        params = [request.origin, request.destination]
        date_key = 'all'
        if request.HasField('date'):
            try:
                date = request.date.ToDatetime()
            except ValueError:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Invalid date')
            if date.time() != time.min:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'Date must be midnight UTC')
            date_key = date.date().isoformat()
            sql += ' AND departure_time >= %s AND departure_time < %s'
            params.extend([date, date + timedelta(days=1)])
        sql += ' ORDER BY departure_time, flight_id'

        key = f'search:{request.origin}:{request.destination}:{date_key}'
        with cache_lock:
            cached = get_cached(key, flight_pb2.SearchFlightsResponse)
            if cached is not None:
                return cached
            with connect() as conn:
                rows = conn.execute(sql, params).fetchall()
            flights = []
            for row in rows:
                flights.append(flight_message(row))
            response = flight_pb2.SearchFlightsResponse(flights=flights)
            set_cached(key, response)
            return response

    def GetFlight(self, request, context):
        check_api_key(context)
        key = f'flight:{request.flight_id}'
        with cache_lock:
            cached = get_cached(key, flight_pb2.Flight)
            if cached is not None:
                return cached
            with connect() as conn:
                row = conn.execute('SELECT * FROM flight WHERE flight_id = %s', (request.flight_id,)).fetchone()
            if row is None:
                return context.abort(grpc.StatusCode.NOT_FOUND, 'Flight not found')
            response = flight_message(row)
            set_cached(key, response)
            return response

    def ReserveSeats(self, request, context):
        check_api_key(context)
        if request.seat_count <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'seat_count must be positive')

        try:
            with connect() as conn:
                row = conn.execute('SELECT * FROM seat_reserve WHERE booking_id = %s', (request.booking_id,)).fetchone()
                if row is None:
                    flight = conn.execute(
                        'SELECT available_seats FROM flight WHERE flight_id = %s FOR UPDATE',
                        (request.flight_id,),
                    ).fetchone()
                    if flight is None:
                        return context.abort(grpc.StatusCode.NOT_FOUND, 'Flight not found')
                    if flight['available_seats'] < request.seat_count:
                        return context.abort(grpc.StatusCode.RESOURCE_EXHAUSTED, 'Not enough seats')
                    conn.execute(
                        'UPDATE flight SET available_seats = available_seats - %s WHERE flight_id = %s',
                        (request.seat_count, request.flight_id),
                    )
                    row = conn.execute(
                        "INSERT INTO seat_reserve (flight_id, booking_id, seat_count, status) "
                        "VALUES (%s, %s, %s, 'ACTIVE') RETURNING *",
                        (request.flight_id, request.booking_id, request.seat_count),
                    ).fetchone()
                    if row is None:
                        raise RuntimeError('Reservation insert returned no row')
        except (SerializationFailure, UniqueViolation):
            # Параллельный повтор мог уже создать эту резервацию. Наша транзакция откатилась.
            with connect() as conn:
                row = conn.execute('SELECT * FROM seat_reserve WHERE booking_id = %s', (request.booking_id,)).fetchone()
            if row is None:
                raise

        if row['flight_id'] != request.flight_id or row['seat_count'] != request.seat_count:
            return context.abort(grpc.StatusCode.INVALID_ARGUMENT, 'booking_id already used with different parameters')
        invalidate(request.flight_id)
        return reservation_message(row)

    def ReleaseReservation(self, request, context):
        check_api_key(context)
        try:
            with connect() as conn:
                row = conn.execute(
                    "UPDATE seat_reserve SET status = 'RELEASED' "
                    "WHERE booking_id = %s AND status = 'ACTIVE' RETURNING flight_id, seat_count",
                    (request.booking_id,),
                ).fetchone()
                if row is not None:
                    conn.execute(
                        'UPDATE flight SET available_seats = available_seats + %s WHERE flight_id = %s',
                        (row['seat_count'], row['flight_id']),
                    )
                else:
                    row = conn.execute(
                        "SELECT flight_id FROM seat_reserve WHERE booking_id = %s AND status = 'RELEASED'",
                        (request.booking_id,),
                    ).fetchone()
                    if row is None:
                        return context.abort(grpc.StatusCode.NOT_FOUND, 'Active reservation not found')
        except SerializationFailure:
            with connect() as conn:
                row = conn.execute(
                    "SELECT flight_id FROM seat_reserve WHERE booking_id = %s AND status = 'RELEASED'",
                    (request.booking_id,),
                ).fetchone()
            if row is None:
                raise
        invalidate(row['flight_id'])
        return Empty()


def main():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    flight_pb2_grpc.add_FlightServiceServicer_to_server(FlightService(), server)
    server.add_insecure_port('0.0.0.0:' + os.environ.get('GRPC_PORT', '50051'))
    server.start()
    server.wait_for_termination()


if __name__ == '__main__':
    main()
