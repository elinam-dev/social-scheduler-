import time
import uuid
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Job
from app.db.session import get_session
from app.schemas.job import JobRead

router = APIRouter(tags=["jobs"])


def _job_event_stream(job_id: uuid.UUID, engine: Engine) -> Iterator[str]:
    last_payload: str | None = None
    idle_polls = 0
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    while True:
        with session_factory() as session:
            job = session.get(Job, job_id)
            if job is None:
                return

            snapshot = JobRead.model_validate(job)
        payload = snapshot.model_dump_json()
        terminal = snapshot.status in {"succeeded", "failed"}

        if payload != last_payload:
            yield f"data: {payload}\n\n"
            last_payload = payload
            idle_polls = 0
        else:
            idle_polls += 1
            if idle_polls >= 15:
                yield ": keep-alive\n\n"
                idle_polls = 0

        if terminal:
            return

        time.sleep(1)


@router.get("/jobs/{job_id}/events")
def stream_job_events(
    job_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> StreamingResponse:
    if session.get(Job, job_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    return StreamingResponse(
        _job_event_stream(job_id, session.get_bind()),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/jobs/{job_id}", response_model=JobRead)
def get_job(
    job_id: uuid.UUID,
    session: Session = Depends(get_session),
) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )
    return job
