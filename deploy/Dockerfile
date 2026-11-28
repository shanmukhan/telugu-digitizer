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
    HOME=/home/appuser \
    OMP_NUM_THREADS=2 \
    OPENBLAS_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    PROXY_HEADERS=true \
    FORWARDED_ALLOW_IPS=127.0.0.1

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

# Download official Tesseract Telugu tessdata_best model with SHA-256 verification
RUN mkdir -p /app/models/tesseract/tessdata /app/models/lexicon \
  && curl -fsSL https://github.com/tesseract-ocr/tessdata_best/raw/main/tel.traineddata \
       -o /app/models/tesseract/tessdata/tel.traineddata \
  && echo "81b0a1cfaf8bbf0f87da72b8c348264c6f24130766f5c4ade733fc20c05aaccc  /app/models/tesseract/tessdata/tel.traineddata" | sha256sum -c -

COPY pyproject.toml alembic.ini ./
COPY alembic/ ./alembic/
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist
COPY deploy/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

ARG BUILD_LEXICON=true
RUN if [ "$BUILD_LEXICON" = "true" ]; then \
      python scripts/build_telugu_lexicon.py --output /app/models/lexicon/telugu_lexicon.tsv.gz \
      && python scripts/build_telugu_dictionary_db.py --lexicon /app/models/lexicon/telugu_lexicon.tsv.gz --output /app/models/lexicon/telugu_dictionary.sqlite; \
    fi

RUN groupadd --gid 1000 appuser \
  && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash appuser \
  && chmod +x /usr/local/bin/docker-entrypoint.sh \
  && python -m pip install -e . --no-deps \
  && mkdir -p /app/workspace /home/appuser/.paddlex \
  && chown -R appuser:appuser /app /home/appuser

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)"

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
