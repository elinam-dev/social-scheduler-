from fastapi import FastAPI

app = FastAPI(title="Local AI Video Clipper API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
