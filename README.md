# Local AI Video Clipper

Self-hosted video clipping that transcribes long-form video, finds and ranks
short segments, renders vertical clips with captions, and provides them for
review and download. The application runs locally with Docker Compose; the
default language-model integration is Ollama. Only process videos you own or
have permission to use.

## Features

- FastAPI service, Redis/RQ worker, PostgreSQL, and MinIO object storage.
- Local transcription with faster-whisper, word timestamps, and speaker
  diarization. CPU is supported; NVIDIA acceleration is optional.
- Sentence-aligned candidate selection, LLM review, multi-signal ranking, and
  generated titles.
- FFmpeg rendering with face-following crops, blurred-background and split-screen
  fallbacks, selectable aspect ratios, and word-timed ASS captions.
- Local Next.js UI for upload progress, job updates, clip previews, trim and
  caption-style changes, rerendering, and individual or ZIP downloads.
- Optional public-URL ingestion with an explicit rights confirmation.

## Requirements

- Docker Engine/Desktop with the Docker Compose v2 plugin.
- Node.js and npm to run the web app.
- A machine with enough memory and disk for the selected Whisper and diarization
  models, source videos, and rendered clips. CPU works but model inference may be
  slow; GPU is optional.
- A Hugging Face read token for pyannote diarization after accepting the terms
  for `pyannote/speaker-diarization-3.1` and its linked models.

## Quick start

1. Clone the repository and create the ignored local environment file:

   ```powershell
   Copy-Item .env.example .env
   ```

   On Linux/macOS, use `cp .env.example .env`. The example credentials are for
   local development only. Keep `.env` private and do not expose the services to
   an untrusted network.

2. Set `CLIPPER_HF_TOKEN` in `.env` to your Hugging Face read token. You must
   accept the model terms on Hugging Face before diarization can run.

3. Start the application services from the repository root:

   ```sh
   docker compose up --build
   ```

   The API is at <http://localhost:8001>, its interactive docs are at
   <http://localhost:8001/docs>, and the MinIO console is at
   <http://localhost:9001>. Compose binds service ports to localhost by default.
   The API applies database migrations during startup.

4. In a second terminal, start the local Ollama model service and download the
   default model:

   ```sh
   docker compose --profile llm up -d ollama
   docker compose exec ollama ollama pull llama3.2
   ```

   The first model and Whisper runs download model weights into persistent Docker
   volumes and can take time. If you use another Ollama model, set
   `CLIPPER_LLM_MODEL` in `.env` and pull that model instead.

5. Start the web app in another terminal:

   ```powershell
   cd apps/web
   npm ci
   Copy-Item env.local.example .env.local
   npm run dev
   ```

   On Linux/macOS, use `cp env.local.example .env.local`. Open
   <http://localhost:3000>, create a project, and upload a
   rights-cleared video. For URL ingestion, submit a supported public HTTP(S)
   URL and confirm you have rights to process it.

The default Whisper model is `small` with CPU int8 inference when CUDA is not
available. Processing time depends on video duration, model downloads, and
hardware. Clips are created from sentence-aligned candidates; videos without
enough usable speech may produce fewer clips or none.

## GPU and performance

For an NVIDIA GPU, install NVIDIA Container Toolkit (or enable GPU support in
Docker Desktop on Windows), then start the stack with the GPU Compose override:

```sh
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

To use a different Whisper model, set `CLIPPER_WHISPER_MODEL` in `.env`. Worker
replicas can process jobs concurrently; set `CLIPPER_WORKER_REPLICAS` before
starting/recreating the worker. Each replica may load its own inference models,
so increasing replicas can sharply increase RAM or VRAM use.

## Local development and tests

The API and worker images use Python 3.11. Create and activate a Python 3.11
virtual environment, then install the development requirements:

```sh
python -m pip install -r services/api/requirements-dev.txt -r services/worker/requirements.txt pre-commit
```

Run the project checks from the repository root:

```sh
make lint
make format-check
make test
```

The integration test exercises upload, queued processing, rendering, state
updates, and clip download with in-memory storage and mocked model inference;
it does not require downloading inference models. Additional API and worker
details are in [docs/API.md](./docs/API.md). Evaluation cases use a placeholder
manifest in `eval/`; add only rights-cleared evaluation videos.

## Configuration and data

`.env.example` lists the Compose settings. Important options include:

| Variable | Purpose | Default |
| --- | --- | --- |
| `API_PORT` | Host port for the API | `8001` |
| `CLIPPER_WHISPER_MODEL` | faster-whisper model | `small` |
| `CLIPPER_WORKER_REPLICAS` | Number of worker replicas | `1` |
| `CLIPPER_HF_TOKEN` | Hugging Face token for diarization | empty |
| `CLIPPER_LLM_PROVIDER` | `ollama` or `openai-compatible` | `ollama` |
| `CLIPPER_LLM_MODEL` | Configured LLM model name | `llama3.2` |

The OpenAI-compatible provider is optional. It sends requests to the configured
remote endpoint and requires its own credentials; the default Ollama provider
runs locally. Keep API keys in the ignored `.env` file, never in source control.

PostgreSQL, Redis, MinIO, Ollama, and model caches use named Docker volumes.
`docker compose down` stops the stack but keeps that data. **`docker compose
down --volumes` permanently deletes the database, stored videos/renders, and
cached model weights.**

## Scope and limitations

- The app is intended for local/self-hosted use; the API does not provide
  user-authentication for deployment on a public network.
- Generated clip scores and speaker-to-face matching are heuristics. Review
  clips before publishing.
- Saved clip titles appear as a short optional on-screen hook overlay. B-roll is
  not sourced or inserted automatically.
- Scheduled publishing is not implemented. Export clips and publish them using
  a platform account you control.
- See [docs/DECISIONS.md](./docs/DECISIONS.md) for implementation decisions and
  known trade-offs.
