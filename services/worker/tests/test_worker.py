from clipper_worker import worker


def test_worker_bootstrap_configures_json_logging_and_default_queue(
    monkeypatch,
) -> None:
    actions: list[str] = []
    captured: dict[str, object] = {}

    class FakeRedis:
        @staticmethod
        def from_url(url: str) -> object:
            actions.append("redis")
            captured["redis_url"] = url
            return object()

    class FakeQueue:
        def __init__(self, name: str, *, connection: object) -> None:
            actions.append("queue")
            captured["queue_name"] = name
            captured["queue_connection"] = connection

    class FakeWorker:
        def __init__(self, queues: list[FakeQueue], *, connection: object) -> None:
            actions.append("worker")
            captured["queues"] = queues
            captured["worker_connection"] = connection

        def work(self) -> None:
            actions.append("work")

    monkeypatch.setenv("REDIS_URL", "redis://test:6379/0")
    monkeypatch.setattr(worker, "configure_logging", lambda: actions.append("logging"))
    monkeypatch.setattr(worker, "Redis", FakeRedis)
    monkeypatch.setattr(worker, "Queue", FakeQueue)
    monkeypatch.setattr(worker, "Worker", FakeWorker)

    worker.main()

    assert actions == ["logging", "redis", "queue", "worker", "work"]
    assert captured["redis_url"] == "redis://test:6379/0"
    assert captured["queue_name"] == "default"
    assert captured["queue_connection"] is captured["worker_connection"]
