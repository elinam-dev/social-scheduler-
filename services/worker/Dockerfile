FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_RETRIES=5 \
    REDIS_URL=redis://redis:6379/0

RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg tini \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /usr/sbin/nologin app
RUN mkdir /models && chown app:app /models

WORKDIR /app

COPY services/worker/requirements.txt /app/requirements.txt
ARG CLIPPER_GPU=0
RUN if [ "${CLIPPER_GPU}" = "1" ]; then \
        pip install --no-cache-dir \
            --index-url https://download.pytorch.org/whl/cu128 \
            torch==2.8.0 torchaudio==2.8.0 \
        && pip install --no-cache-dir \
            nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"; \
    else \
        pip install --no-cache-dir \
            --index-url https://download.pytorch.org/whl/cpu \
            torch==2.8.0 torchaudio==2.8.0; \
    fi \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY services/worker/requirements-vision.txt /app/requirements-vision.txt
RUN pip install --no-cache-dir --no-deps -r /app/requirements-vision.txt

COPY services/api/app /app/app
COPY --chown=app:app services/worker /app
USER app

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sh", "-c", "export LD_LIBRARY_PATH=\"/usr/local/lib/python3.11/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.11/site-packages/nvidia/cudnn/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}\"; exec rq worker --url \"$REDIS_URL\" default"]
