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

The worker groups transcript words into sentences at punctuation or pauses longer
than one second, and detects audio silences with FFmpeg (default threshold `-35
dB` for at least `0.5` seconds). Candidate generation enumerates contiguous
sentence ranges from 30 to 90 seconds. Proposed clip times snap to the closest
non-empty sentence-aligned range. Preliminary candidate ranking averages the
four review scores; final ranking uses the combined multi-signal score. Highly
overlapping candidates are deduplicated using overlap divided by the shorter
candidate duration (default threshold `0.7`) before keeping the top ten. Final
candidate scores combine the mean LLM review, normalized PCM audio
energy, speech-rate fit, and explicit laughter markers in the transcript. The
initial weights and normalization ranges are recorded in [DECISIONS.md](./DECISIONS.md)
and are intended to be tuned against the evaluation set.
Each reviewed clip can also receive an 80-character title and 120-character
on-screen hook, both required to remain grounded in the transcript.

Clip rendering uses FFmpeg timestamp trim filters with video re-encoding rather
than keyframe-only stream copying. The video filter selects source frames within
the requested interval (so boundaries resolve to actual frame timestamps), while
audio is trimmed to the requested sample times.

Clip-selection LLM clients are configured through `CLIPPER_LLM_PROVIDER` and
`CLIPPER_LLM_MODEL`. The default provider is local Ollama. Start the optional
Compose service and download the configured model with:

```sh
docker compose --profile llm up -d ollama
docker compose exec ollama ollama pull llama3.2
```

To use an OpenAI-compatible backend instead, set
`CLIPPER_LLM_PROVIDER=openai-compatible`, its model and base URL, and
`CLIPPER_LLM_API_KEY` in the ignored `.env` file. An API key is only sent when
this provider is explicitly selected. Candidate review expects JSON scores from
0 to 1 for hook strength, standalone coherence, payoff, and pacing, plus a
standalone flag and rationale. Invalid JSON or schema values are retried up to
three attempts; network and provider failures are reported immediately.
