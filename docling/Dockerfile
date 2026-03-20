# Optional local build when you cannot pull from ghcr.io/quay.io.
# Default stack uses the official image: ghcr.io/docling-project/docling-serve-cpu (see docker-compose.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    DOCLING_HOST=0.0.0.0 \
    DOCLING_PORT=5001 \
    DOCLING_WORKERS=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --upgrade pip uv

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=10s --start-period=180s --retries=5 \
    CMD sh -c 'curl -fsS "http://127.0.0.1:${DOCLING_PORT}/health" >/dev/null || exit 1'

CMD ["sh", "-c", "uvx --from 'docling-serve==1.5.0' --with onnxruntime --with docling-core==2.48.1 --with opencv-python-headless docling-serve run --host ${DOCLING_HOST} --port ${DOCLING_PORT} --workers ${DOCLING_WORKERS}"]
