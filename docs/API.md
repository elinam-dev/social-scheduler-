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
inference. Audio longer than 30 minutes is split into temporary 30-minute chunks;
segment and word timestamps are offset back to the original audio timeline. Only
upload videos that you own or have permission to process.

Speaker diarization uses pyannote locally. Before processing uploads, accept the
Hugging Face terms for `pyannote/speaker-diarization-3.1` and its linked models,
create a read token, and place it in `CLIPPER_HF_TOKEN` in your untracked `.env`
file. Do not commit that token.

Completed jobs store the validated transcript JSON on the video record. Retrieve
it with `GET /videos/{video_id}/transcript`; the response contains the detected
language and confidence, duration, segments, word timestamps and confidence, and
speaker IDs. The endpoint returns `409` while transcription is not yet available.
