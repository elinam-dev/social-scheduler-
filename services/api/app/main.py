import logging
from time import perf_counter

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from app.api.routes.clips import router as clips_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.projects import router as projects_router
from app.api.routes.videos import router as videos_router
from app.config import Settings
from app.logging_config import configure_logging

configure_logging()
settings = Settings()
app = FastAPI(title=settings.project_name)
logger = logging.getLogger(__name__)
app.include_router(projects_router)
app.include_router(jobs_router)
app.include_router(clips_router)
app.include_router(videos_router)


@app.middleware("http")
async def log_request(request: Request, call_next: RequestResponseEndpoint) -> Response:
    start = perf_counter()
    try:
        response = await call_next(request)
    except Exception as error:
        logger.exception(
            "HTTP request failed",
            extra={
                "event": "http_request",
                "method": request.method,
                "path": request.url.path,
                "duration_ms": round((perf_counter() - start) * 1000, 2),
                "status": "failed",
                "error_type": type(error).__name__,
            },
        )
        raise
    logger.info(
        "HTTP request completed",
        extra={
            "event": "http_request",
            "method": request.method,
            "path": request.url.path,
            "duration_ms": round((perf_counter() - start) * 1000, 2),
            "status": "completed",
            "status_code": response.status_code,
        },
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
