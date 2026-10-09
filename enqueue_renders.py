# NOTE: Rendering is now automatic after video processing completes via _enqueue_render_jobs in tasks.py.
import uuid, os, sys
sys.path.insert(0, "/app")
from redis import Redis
from rq import Queue, Retry
from rq.job import Callback
from app.db.session import SessionLocal
from app.db.models import Clip, Job

clip_ids = [
    "407ebaf7-adeb-4b55-8396-96f0b730b026",
    "0b103d4c-f3db-430f-afd2-7f86817bdffd",
    "bdf52bb7-c486-4513-a24d-dcfd31859b6f",
    "7f0f00a6-94a7-40a6-bf15-696a1184f55a",
    "6fba7b52-f500-40bb-b4b5-f1309824e642",
    "384954ee-c5ce-461e-b029-124f5e603d58",
    "203ca33a-c9a6-4b09-8889-59be390785b0",
    "e37bee99-3407-40ec-826f-9b80aa38904b",
    "a21307ca-7b2e-46c8-bff2-7ea7998eb3b4",
]
video_id = uuid.UUID("d3ab65d0-6f03-4829-89b9-c1c384507fe6")
project_id = uuid.UUID("40ea21fc-0428-4556-a709-be59c90d83d6")

conn = Redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
q = Queue("render", connection=conn)

JOB_RETRY_POLICY = Retry(max=2, interval=[30, 120])

for clip_id in clip_ids:
    job_id = uuid.uuid4()
    with SessionLocal() as session:
        clip = session.get(Clip, uuid.UUID(clip_id))
        if clip is None:
            print(f"Clip not found: {clip_id}")
            continue
        job = Job(id=job_id, project_id=project_id, video_id=video_id, job_type="render_clip", rq_job_id=str(job_id))
        clip.status = "rendering"
        session.add(job)
        session.commit()
    q.enqueue("clipper_worker.tasks.render_clip_job", clip_id, str(job_id),
              job_id=str(job_id), job_timeout=21600,
              retry=JOB_RETRY_POLICY,
              on_failure=Callback("clipper_worker.tasks.mark_clip_render_failed"))
    print(f"Enqueued render for {clip_id}")

print("Done - 9 render jobs queued")
