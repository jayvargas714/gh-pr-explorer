"""In-memory TTL cache decorator."""

import time
from functools import wraps

from flask import request

from backend.config import get_config
from backend.extensions import cache


def cached(ttl_seconds=None):
    """Decorator for caching function results with TTL."""
    if ttl_seconds is None:
        ttl_seconds = get_config().get("cache_ttl_seconds", 300)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            qs = request.query_string.decode() if request else ''
            cache_key = f"{func.__name__}:{args}:{sorted(kwargs.items())}:{qs}"
            now = time.time()

            if cache_key in cache:
                result, timestamp = cache[cache_key]
                if now - timestamp < ttl_seconds:
                    return result

            result = func(*args, **kwargs)
            cache[cache_key] = (result, now)
            return result

        return wrapper

    return decorator
