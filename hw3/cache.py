import os
import threading

import redis


client = redis.Redis.from_url(os.environ['REDIS_URL'])
CACHE_TTL = 300
cache_lock = threading.Lock()


def get_cached(key, message_type):
    data = client.get(key)
    if data is not None:
        print('cache hit:', key, flush=True)
        return message_type.FromString(data)
    print('cache miss:', key, flush=True)
    return None


def set_cached(key, message):
    client.set(key, message.SerializeToString(), ex=CACHE_TTL)


def invalidate(flight_id):
    with cache_lock:
        client.delete(f'flight:{flight_id}')
        for key in client.scan_iter(match='search:*'):
            client.delete(key)
