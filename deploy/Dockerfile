# Stage 1: Build the React + TypeScript frontend bundle
FROM node:22-bookworm-slim AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Runtime API + OCR worker image (supports linux/arm64 for Raspberry Pi and linux/amd64)
FROM python:3.11-slim-bookworm

ARG BUILD_PADDLE=true

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OMP_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    PROXY_HEADERS=true \
    FORWARDED_ALLOW_IPS=*

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    fonts-noto-core \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    tesseract-ocr \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY deploy/requirements.runtime.txt ./deploy/requirements.runtime.txt
RUN python -m pip install --upgrade pip setuptools wheel \
  && python -m pip install -r ./deploy/requirements.runtime.txt

RUN if [ "$BUILD_PADDLE" = "true" ]; then \
      python -m pip install "paddlepaddle==3.3.1" -i https://www.paddlepaddle.org.cn/packages/stable/cpu/ \
      && python -m pip install "paddleocr==3.7.0"; \
    fi

# Download official Tesseract Telugu tessdata_best model
RUN mkdir -p /app/models/tesseract/tessdata \
  && curl -fsSL https://github.com/tesseract-ocr/tessdata_best/raw/main/tel.traineddata \
       -o /app/models/tesseract/tessdata/tel.traineddata

COPY pyproject.toml alembic.ini ./
COPY alembic/ ./alembic/
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist
COPY deploy/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
  && python -m pip install -e . --no-deps \
  && mkdir -p /app/workspace

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
