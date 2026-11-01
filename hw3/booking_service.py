import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import grpc

from db import connect
from grpc_client import call_flight
from proto import flight_pb2, flight_pb2_grpc


class ApiError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


def flight_dict(flight):
    return {
        'flight_id': flight.flight_id,
        'flight_number': flight.flight_number,
        'airline': flight.airline,
        'origin': flight.origin,
        'destination': flight.destination,
        'departure_time': flight.departure_time.ToJsonString(),
        'arrival_time': flight.arrival_time.ToJsonString(),
        'total_seats': flight.total_seats,
        'available_seats': flight.available_seats,
        'price': flight.price,
        'status': flight_pb2.FlightStatus.Name(flight.status),
    }


class BookingHandler(BaseHTTPRequestHandler):
    stub: flight_pb2_grpc.FlightServiceStub
    metadata = ()

    def do_GET(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def handle_request(self):
        try:
            url = urlparse(self.path)
            path = url.path.strip('/').split('/')
            query = parse_qs(url.query)
            body = {}
            if self.command == 'POST':
                length = int(self.headers.get('Content-Length', '0'))
                if length:
                    body = json.loads(self.rfile.read(length))
            status, data = self.route(path, query, body)
        except ApiError as error:
            status, data = error.status, {'error': error.message}
        except (ValueError, KeyError, TypeError):
            status, data = 400, {'error': 'Invalid request'}
        except grpc.RpcError as error:
            codes = {
                grpc.StatusCode.NOT_FOUND: 404,
                grpc.StatusCode.INVALID_ARGUMENT: 400,
                grpc.StatusCode.RESOURCE_EXHAUSTED: 409,
            }
            status = codes.get(error.code(), 502)
            data = {'error': error.details()}

        content = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def route(self, path, query, body):
        if self.command == 'GET' and path == ['flights']:
            request = flight_pb2.SearchFlightsRequest(origin=query['origin'][0], destination=query['destination'][0])
            if 'date' in query:
                request.date.FromDatetime(datetime.strptime(query['date'][0], '%Y-%m-%d'))
            response = call_flight(self.stub.SearchFlights, request, self.metadata)
            return 200, [flight_dict(flight) for flight in response.flights]

        if self.command == 'GET' and len(path) == 2 and path[0] == 'flights':
            flight = call_flight(self.stub.GetFlight, flight_pb2.GetFlightRequest(flight_id=int(path[1])), self.metadata)
            return 200, flight_dict(flight)

        if self.command == 'POST' and path == ['bookings']:
            return 201, self.create_booking(body)

        if self.command == 'GET' and path == ['bookings']:
            with connect() as conn:
                rows = conn.execute('SELECT * FROM book WHERE user_id = %s ORDER BY booking_id', (int(query['user_id'][0]),)).fetchall()
            return 200, rows

        if self.command == 'GET' and len(path) == 2 and path[0] == 'bookings':
            with connect() as conn:
                row = conn.execute('SELECT * FROM book WHERE booking_id = %s', (int(path[1]),)).fetchone()
            if row is None:
                raise ApiError(404, 'Booking not found')
            return 200, row

        if self.command == 'POST' and len(path) == 3 and path[0] == 'bookings' and path[2] == 'cancel':
            return 200, self.cancel_booking(int(path[1]))

        raise ApiError(404, 'Endpoint not found')

    def create_booking(self, body):
        user_id = int(body['user_id'])
        flight_id = int(body['flight_id'])
        seat_count = int(body['seat_count'])
        passenger_name = body['passenger_name']
        passenger_email = body['passenger_email']
        if seat_count <= 0:
            raise ApiError(400, 'seat_count must be positive')

        flight = call_flight(self.stub.GetFlight, flight_pb2.GetFlightRequest(flight_id=flight_id), self.metadata)
        with connect() as conn:
            # Получаем ID из sequence, но само бронирование пока не создаём.
            row = conn.execute("SELECT nextval(pg_get_serial_sequence('book', 'booking_id')) AS booking_id").fetchone()
            booking_id = row['booking_id']
            call_flight(self.stub.ReserveSeats, flight_pb2.ReserveSeatsRequest(
                flight_id=flight_id, seat_count=seat_count, booking_id=booking_id,
            ), self.metadata)
            row = conn.execute(
                'INSERT INTO book (booking_id, user_id, flight_id, passenger_name, passenger_email, seat_count, total_price, status) '
                "VALUES (%s, %s, %s, %s, %s, %s, %s, 'CONFIRMED') RETURNING *",
                (booking_id, user_id, flight_id, passenger_name, passenger_email, seat_count, seat_count * flight.price),
            ).fetchone()
        return row

    def cancel_booking(self, booking_id):
        with connect() as conn:
            row = conn.execute('SELECT * FROM book WHERE booking_id = %s', (booking_id,)).fetchone()
            if row is None:
                raise ApiError(404, 'Booking not found')
            if row['status'] != 'CONFIRMED':
                raise ApiError(409, 'Booking is already cancelled')
            call_flight(self.stub.ReleaseReservation, flight_pb2.ReleaseReservationRequest(booking_id=booking_id), self.metadata)
            row = conn.execute(
                "UPDATE book SET status = 'CANCELLED' WHERE booking_id = %s RETURNING *",
                (booking_id,),
            ).fetchone()
        return row


def main():
    channel = grpc.insecure_channel(os.environ.get('FLIGHT_SERVICE_ADDR', 'localhost:50051'))
    grpc.channel_ready_future(channel).result()
    BookingHandler.stub = flight_pb2_grpc.FlightServiceStub(channel)
    BookingHandler.metadata = (('x-api-key', os.environ['FLIGHT_API_KEY']),)
    server = ThreadingHTTPServer(('0.0.0.0', int(os.environ.get('HTTP_PORT', '8080'))), BookingHandler)
    server.serve_forever()


if __name__ == '__main__':
    main()
