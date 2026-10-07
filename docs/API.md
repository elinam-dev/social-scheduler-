# API and upload flow

Start the local stack from the repository root:

```sh
docker compose up --build
```

The API is available at `http://localhost:8001`; interactive API documentation is
at `http://localhost:8001/docs`. Compose applies Alembic migrations before starting
the API. The worker consumes queued jobs from Redis and stores source videos and
extracted audio in MinIO.

The default worker image uses CPU-only PyTorch, and Whisper uses CPU int8 when no
CUDA device is visible. For an NVIDIA GPU, install NVIDIA Container Toolkit
(Docker Desktop GPU support on Windows), then start with
`docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build`.
The GPU override builds CUDA 12.8 PyTorch and exposes available GPUs to the
worker; Whisper and pyannote automatically select CUDA when detected. Use the
default Compose command on CPU-only machines.

The worker handles one queued job at a time. To process queued videos and clip
renders concurrently, set `CLIPPER_WORKER_REPLICAS=2` (or another value) in
`.env` and run `docker compose up -d --build worker`. Each replica can load its
own Whisper and diarization models, so increase this only when the machine has
enough RAM or GPU memory. The default is one replica.

The Next.js web app lives in `apps/web`. Run `npm ci`, copy
`apps/web/env.local.example` to `apps/web/.env.local`, then run `npm run dev` from
`apps/web`. The web server
proxies `/backend-api/*` to the configured API address so browser requests remain
same-origin. Its typed endpoint client is in `apps/web/src/lib/api.ts`.

The web app is available at `http://localhost:3000`; create a project and upload
a video there to follow upload-byte progress and live processing updates.
Alternatively, create a project and upload a video through the API:

```sh
curl -X POST http://localhost:8001/projects \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"My project\"}"

curl -X POST http://localhost:8001/projects/PROJECT_ID/videos \
  -F "file=@/path/to/video.mp4"

curl http://localhost:8001/jobs/JOB_ID
```

To import a supported public video URL, POST JSON to
`/projects/{project_id}/videos/url` with `url` and `rights_confirmed: true`.
Only submit videos you own or have permission to process. URL downloads happen
inside the worker, and only publicly reachable HTTP(S) hosts are accepted.

The upload response includes both the saved video and its queued job. Job states
are `queued`, `running`, `succeeded`, and `failed`; processing records duration,
dimensions, frame rate, and the MinIO key for extracted 16 kHz mono WAV audio.
Processing and rendering jobs retry up to twice after failures, waiting 30
seconds before the first retry and 120 seconds before the second. Failures are
shown as terminal only after retries are exhausted. Worker-local download,
transcription, and rendering files are stored in temporary directories and
removed when each task exits, including on failure.
The web app receives browser upload progress and then subscribes to
`GET /jobs/{job_id}/events`, a server-sent event stream that emits job updates
until processing succeeds or fails. Clients can also poll `GET /jobs/{job_id}`.
After processing, the web app requests ranked clip metadata from
`GET /videos/{video_id}/clips`; ready clips include a preview URL at
`GET /clips/{clip_id}/preview`. Previews are streamed from MinIO and support
HTTP byte ranges for playback seeking. A video with no saved clip records
returns an empty list. `PATCH /clips/{clip_id}/trim` saves validated start/end
seconds for the transcript editor; changing boundaries marks the clip pending
until a new render is produced. `PATCH /clips/{clip_id}/caption-style` saves a
built-in caption style (`default`, `minimal`, or `word-highlight`) and likewise
marks a changed clip pending until it is rendered again. The
`POST /clips/{clip_id}/render` endpoint queues an individual captioned render
and returns a job that can be monitored through the same SSE endpoint. Rerender
uses the clip's saved boundaries, aspect ratio, transcript word timing, and
caption preset. It currently uses the blurred-background layout while preserving
source audio when present. Download a ready clip as an attachment with
`GET /clips/{clip_id}/download`. `GET /videos/{video_id}/clips/download`
creates a ZIP containing every currently ready clip; it returns a conflict if
there are no rendered clips to include.
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
Face detection uses MediaPipe locally and returns normalized face boxes with
frame timestamps and confidence scores. Frames are sampled at a configurable
interval (one second by default); no external model download or cloud service is
required. A greedy intersection-over-union tracker links detections between
samples into deterministic face tracks, with configurable overlap and maximum
gap thresholds. Diarized speaker turns can be associated with tracks by temporal
co-occurrence. This is a local heuristic, not lip-reading or proof of who is
speaking; inspect associations for multi-person shots. A smoothed crop path can
follow a selected face track, emitting even-pixel, in-bounds crop rectangles at
each detected timestamp for vertical output. FFmpeg can render a clip through
that timestamp-interpolated path to 9:16 H.264/AAC MP4, retaining trimmed audio
when present. If no reliable face crop is available, the renderer also supports
a blurred-background fit and a split-screen layout that stacks the source's left
and right halves into separate panels. The face-following crop renderer also
offers 9:16 (1080x1920), 1:1 (1080x1080), and 16:9 (1920x1080) exports.

Caption chunks are generated from word timestamps, splitting at sentence ends,
long pauses, speaker changes, and configurable word or duration limits. Each
chunk retains its original timed words for subtitle rendering and highlighting.
Chunks can be serialized to ASS subtitles with configurable play resolution and
clip-time rebasing; subtitle text is escaped to prevent accidental ASS tags.
Built-in ASS styles include default, minimal, and word-by-word karaoke
highlighting driven by the original word timing. Callers can optionally pass
keywords for case-insensitive color emphasis and an explicit keyword-to-emoji
mapping; no emoji are inserted by default. Renderers accept an ASS subtitle path
to burn captions into regular trims, face-following exports, or either fallback
layout. When a rendered clip has a saved title, it is also displayed as a top-centered
hook overlay for up to the first 2.5 seconds; the overlay is omitted when the
title is empty.
Custom styles use strict version-1 JSON; the checked-in
`services/worker/caption-templates/word-highlight.json` is an example and can be
loaded with the worker's caption style loader.

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

API and worker application logs are emitted as newline-delimited JSON. Request
records include the HTTP method, path, status code, and duration; worker
`pipeline_operation` records include the operation name, outcome, entity ID, and
duration in milliseconds. Exception records include the exception type and
traceback. URL strings in log messages and tracebacks are redacted, and HTTP
request records omit query strings.

The integration test `services/worker/tests/test_pipeline_integration.py`
exercises upload, queued transcription, clip rendering, job status updates, and
clip download using local in-memory storage and mocked model inference. It is
included in `make test`; to run it alone, execute
`pytest tests/test_pipeline_integration.py` from `services/worker`.
