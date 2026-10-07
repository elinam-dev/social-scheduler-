import os

from redis import Redis
from rq import Queue, Worker

from app.logging_config import configure_logging


def main() -> None:
    configure_logging()
    connection = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    queue = Queue("default", connection=connection)
    Worker([queue], connection=connection).work()


if __name__ == "__main__":
    main()
