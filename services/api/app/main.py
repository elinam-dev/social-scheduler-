from fastapi import FastAPI

from app.config import Settings

settings = Settings()
app = FastAPI(title=settings.project_name)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
