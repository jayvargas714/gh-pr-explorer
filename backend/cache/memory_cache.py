"""In-memory TTL cache decorator backed by cachetools.TTLCache."""

from functools import wraps

from flask import request

from backend.extensions import cache


def cached(ttl_seconds=None):
    """Decorator for caching function results.

    The TTLCache in extensions.py provides bounded eviction (maxsize=256).
    Per-key TTL is handled by the cache itself; the ttl_seconds arg is
    accepted for backward-compat but the global TTL governs expiry.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            qs = request.query_string.decode() if request else ''
            cache_key = f"{func.__name__}:{args}:{sorted(kwargs.items())}:{qs}"

            try:
                return cache[cache_key]
            except KeyError:
                pass

            result = func(*args, **kwargs)
            cache[cache_key] = result
            return result

        return wrapper

    return decorator
