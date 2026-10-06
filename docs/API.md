# API and upload flow

Start the local stack from the repository root:

```sh
docker compose up --build
```

The API is available at `http://localhost:8000`; interactive API documentation is
at `http://localhost:8000/docs`. Compose applies Alembic migrations before starting
the API. The worker consumes queued jobs from Redis and stores source videos and
extracted audio in MinIO.

Create a project, upload a video, and poll its processing job:

```sh
curl -X POST http://localhost:8000/projects \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"My project\"}"

curl -X POST http://localhost:8000/projects/PROJECT_ID/videos \
  -F "file=@/path/to/video.mp4"

curl http://localhost:8000/jobs/JOB_ID
```

The upload response includes both the saved video and its queued job. Job states
are `queued`, `running`, `succeeded`, and `failed`; processing records duration,
dimensions, frame rate, and the MinIO key for extracted 16 kHz mono WAV audio.
Transcription uses the configurable `CLIPPER_WHISPER_MODEL` setting (default
`small`); faster-whisper downloads the selected model on first use and caches its
weights in a persistent Docker volume outside the repository. CPU uses int8
inference. Only upload videos that you own or have permission to process.
