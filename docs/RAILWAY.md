# Railway Deployment Guide

This guide walks you through deploying Social Scheduler on [Railway](https://railway.app).

## Overview

The app consists of 5 services you'll create in the Railway dashboard:

| Service | Type | Source |
|---------|------|--------|
| PostgreSQL | Railway plugin | Built-in |
| Redis | Railway plugin | Built-in |
| MinIO | Custom Docker service | `bitnami/minio` image |
| API | GitHub repo | `services/api/Dockerfile` |
| Worker | GitHub repo | `services/worker/Dockerfile` |
| Web | GitHub repo | `apps/web/` (nixpacks) |

## Prerequisites

- Code pushed to a GitHub repository
- Railway account at [railway.app](https://railway.app)
- Railway **Pro plan** ($5/month) — the free Hobby plan has 512 MB RAM per service, but the Worker needs at least 1 GB for Whisper transcription
- NVIDIA NIM API key from [build.nvidia.com](https://build.nvidia.com) (free tier gives 1000 credits — much faster than running Ollama locally)

## Step-by-Step Setup

### 1. Push code to GitHub

```bash
git add .
git commit -m "Add Railway deployment config"
git push
```

### 2. Create a new Railway project

1. Go to [railway.app](https://railway.app) → **New Project**
2. Select **Deploy from GitHub repo**
3. Choose your repository

### 3. Add PostgreSQL

1. In your project dashboard, click **+ New** → **Database** → **Add PostgreSQL**
2. Railway provisions a Postgres instance and exposes `DATABASE_URL` automatically

### 4. Add Redis

1. Click **+ New** → **Database** → **Add Redis**
2. Railway provisions Redis and exposes `REDIS_URL` automatically

### 5. Add MinIO (custom Docker service)

Railway doesn't have a native MinIO plugin, so deploy it as a Docker service:

1. Click **+ New** → **Empty Service**
2. In the service settings → **Deploy** tab → set **Docker Image** to `bitnami/minio`
3. Add a **Volume**: mount path `/bitnami/minio/data`, size 10 GB (or more)
4. Set these environment variables on the MinIO service:

```
MINIO_ROOT_USER=<choose a username>
MINIO_ROOT_PASSWORD=<choose a strong password>
MINIO_DEFAULT_BUCKETS=videos
```

5. Generate a public domain for MinIO (needed so the API and Worker can reach it)

### 6. Add the API service

1. Click **+ New** → **GitHub Repo** → select your repo
2. Railway may auto-detect the Dockerfile; if not, go to **Settings** → **Build** → set Dockerfile path to `services/api/Dockerfile`
3. Set the start command: `sh -c 'alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 300'`
4. Set these environment variables:

```
CLIPPER_DATABASE_URL=${{Postgres.DATABASE_URL}}
CLIPPER_REDIS_URL=${{Redis.REDIS_URL}}
CLIPPER_OBJECT_STORAGE_ENDPOINT_URL=https://<minio-service>.railway.app
CLIPPER_OBJECT_STORAGE_ACCESS_KEY=<same as MINIO_ROOT_USER>
CLIPPER_OBJECT_STORAGE_SECRET_KEY=<same as MINIO_ROOT_PASSWORD>
CLIPPER_OBJECT_STORAGE_BUCKET=videos
CLIPPER_TOKEN_ENCRYPTION_KEY=<generate — see below>
CLIPPER_PUBLIC_API_URL=https://<api-service>.railway.app
CLIPPER_PROJECT_NAME=Social Scheduler
```

To generate `CLIPPER_TOKEN_ENCRYPTION_KEY`:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> **Railway reference variables** like `${{Postgres.DATABASE_URL}}` auto-fill when services are linked in the same project. Use them exactly as shown — Railway substitutes the real value at deploy time.

5. Generate a public domain for the API service

### 7. Add the Worker service

1. Click **+ New** → **GitHub Repo** → select your repo again
2. Set Dockerfile path to `services/worker/Dockerfile`
3. Set the start command: `python -m clipper_worker.worker`
4. Set these environment variables (all storage/db/redis vars from the API, plus worker-specific ones):

```
CLIPPER_DATABASE_URL=${{Postgres.DATABASE_URL}}
CLIPPER_REDIS_URL=${{Redis.REDIS_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
CLIPPER_OBJECT_STORAGE_ENDPOINT_URL=https://<minio-service>.railway.app
CLIPPER_OBJECT_STORAGE_ACCESS_KEY=<same as MINIO_ROOT_USER>
CLIPPER_OBJECT_STORAGE_SECRET_KEY=<same as MINIO_ROOT_PASSWORD>
CLIPPER_OBJECT_STORAGE_BUCKET=videos
CLIPPER_TOKEN_ENCRYPTION_KEY=<same value as API service>
CLIPPER_WHISPER_MODEL=base
CLIPPER_LLM_PROVIDER=openai-compatible
CLIPPER_LLM_API_BASE_URL=https://integrate.api.nvidia.com/v1
CLIPPER_LLM_API_KEY=<your NVIDIA NIM API key>
CLIPPER_LLM_MODEL=meta/llama-3.1-8b-instruct
CLIPPER_WORKER_REPLICAS=2
HF_HOME=/models
PYANNOTE_CACHE=/models/pyannote
```

> **Why `CLIPPER_WHISPER_MODEL=base`?** The `base` model uses less RAM than `small` and is fast enough on Railway's CPUs. The worker Dockerfile has `ARG CLIPPER_GPU=0` — leave it at 0 for Railway (CPU-only).

> **Why NVIDIA NIM?** Railway doesn't have GPUs on standard plans. NVIDIA NIM runs the LLM in the cloud, so clip generation stays fast without needing Ollama locally. Get a free API key at [build.nvidia.com](https://build.nvidia.com) (1000 free credits).

### 8. Add the Web service

1. Click **+ New** → **GitHub Repo** → select your repo
2. In **Settings** → **Build**, set the **Root Directory** to `apps/web` and builder to **Nixpacks**
3. Set the start command: `npm run start`
4. Set this environment variable:

```
NEXT_PUBLIC_API_URL=https://<api-service>.railway.app
```

5. Generate a public domain for the Web service

### 9. Verify the deployment

1. Check that all services show green in the Railway dashboard
2. Open `https://<api-service>.railway.app/health` — should return `{"status": "ok"}`
3. Open `https://<web-service>.railway.app` — the frontend should load
4. Upload a video and confirm processing completes (worker picks it up from Redis queue)

## Key notes

- **RAM**: Worker needs 1 GB minimum. Railway Pro plan required.
- **MinIO volume**: Without a persistent volume, MinIO data is lost on redeploy. Always attach a volume.
- **Encryption key**: Use the same `CLIPPER_TOKEN_ENCRYPTION_KEY` on both API and Worker — they share session tokens.
- **Turn off your machine**: Once deployed, Railway runs 24/7. Upload a video, close your laptop — the worker will process and post it automatically.
- **Costs**: ~$5/month Pro plan + usage-based compute. MinIO storage is billed per GB. Estimate $10-20/month for moderate use.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Worker OOM crash | Upgrade to Pro plan; ensure at least 1 GB RAM allocated |
| `alembic upgrade head` fails | Check `CLIPPER_DATABASE_URL` is set and Postgres service is running |
| MinIO connection refused | Confirm MinIO has a public domain and the URL in env vars matches exactly |
| Web shows blank page | Check `NEXT_PUBLIC_API_URL` points to the Railway API domain (not localhost) |
| LLM calls fail | Verify `CLIPPER_LLM_API_KEY` is set and NVIDIA NIM credits are not exhausted |
