from functools import lru_cache

from redis import Redis
from rq import Queue, Retry

from app.config import Settings

JOB_RETRY_POLICY = Retry(max=2, interval=[30, 120])


@lru_cache(maxsize=1)
def get_queue() -> Queue:
    settings = Settings()
    return Queue("default", connection=Redis.from_url(settings.redis_url))
