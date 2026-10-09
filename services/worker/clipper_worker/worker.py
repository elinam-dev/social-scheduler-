import os
import threading

from redis import Redis
from rq import Queue, Worker

from app.logging_config import configure_logging


def main() -> None:
    configure_logging()
    connection = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    default_queue = Queue("default", connection=connection)
    render_queue = Queue("render", connection=connection)

    # Start the publish scheduler in a daemon thread
    from clipper_worker.tasks import run_publish_scheduler

    scheduler_thread = threading.Thread(
        target=run_publish_scheduler,
        args=("default",),
        daemon=True,
        name="publish-scheduler",
    )
    scheduler_thread.start()

    Worker([default_queue, render_queue], connection=connection).work()


if __name__ == "__main__":
    main()
