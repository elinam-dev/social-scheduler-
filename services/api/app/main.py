from fastapi import FastAPI

from app.api.routes.clips import router as clips_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.projects import router as projects_router
from app.api.routes.videos import router as videos_router
from app.config import Settings

settings = Settings()
app = FastAPI(title=settings.project_name)
app.include_router(projects_router)
app.include_router(jobs_router)
app.include_router(clips_router)
app.include_router(videos_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
