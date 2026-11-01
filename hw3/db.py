import os

import psycopg
from psycopg.rows import dict_row


def connect():
    conn = psycopg.connect(os.environ['DATABASE_URL'], row_factory=dict_row)
    conn.isolation_level = psycopg.IsolationLevel.SERIALIZABLE
    return conn
