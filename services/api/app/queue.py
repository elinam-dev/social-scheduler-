from functools import lru_cache

from redis import Redis
from rq import Queue

from app.config import Settings


@lru_cache(maxsize=1)
def get_queue() -> Queue:
    settings = Settings()
    return Queue("default", connection=Redis.from_url(settings.redis_url))
