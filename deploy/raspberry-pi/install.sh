#!/usr/bin/env bash
set -euo pipefail

# Native setup script for 64-bit Raspberry Pi OS (aarch64) / Debian Bookworm+ / Ubuntu ARM64.
# Usage:
#   ./deploy/raspberry-pi/install.sh --with-paddle      # Pi 4/5 8GB+ (PaddleOCR 3.3.1 ARM64 + Tesseract)
#   ./deploy/raspberry-pi/install.sh --tesseract-only   # Lower-RAM Pis (2GB/4GB, Tesseract 5 Telugu only)

WITH_PADDLE=true
for arg in "$@"; do
  case "$arg" in
    --with-paddle) WITH_PADDLE=true ;;
    --tesseract-only) WITH_PADDLE=false ;;
    *)
      echo "Unknown option: $arg" >&2
      echo "Usage: $0 [--with-paddle | --tesseract-only]" >&2
      exit 2
      ;;
  esac
done

ARCH="$(uname -m)"
if [[ "$ARCH" != "aarch64" && "$ARCH" != "arm64" && "$ARCH" != "x86_64" ]]; then
  echo "Warning: untested architecture '$ARCH'. Proceeding anyway." >&2
fi

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_DIR"

echo "==> Installing system dependencies (PostgreSQL, Tesseract, Python, fonts)..."
sudo apt-get update
GLIB_PKG="libglib2.0-0"
if apt-cache show libglib2.0-0t64 >/dev/null 2>&1; then
  GLIB_PKG="libglib2.0-0t64"
fi
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  postgresql postgresql-contrib \
  tesseract-ocr libgl1 "${GLIB_PKG}" libgomp1 \
  fonts-noto-core curl git

echo "==> Creating Python virtual environment in .venv..."
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r deploy/requirements.runtime.txt

if [[ "$WITH_PADDLE" == "true" ]]; then
  echo "==> Installing PaddlePaddle 3.3.1 CPU ($ARCH) and PaddleOCR 3.7.0..."
  .venv/bin/python -m pip install "paddlepaddle==3.3.1" -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
  .venv/bin/python -m pip install "paddleocr==3.7.0"
fi

.venv/bin/python -m pip install -e . --no-deps

echo "==> Downloading official tessdata_best Telugu model..."
mkdir -p models/tesseract/tessdata
if [[ ! -f models/tesseract/tessdata/tel.traineddata ]]; then
  curl -fsSL https://github.com/tesseract-ocr/tessdata_best/raw/main/tel.traineddata \
    -o models/tesseract/tessdata/tel.traineddata
fi

if [[ ! -f frontend/dist/index.html ]]; then
  if command -v npm >/dev/null 2>&1; then
    echo "==> Building frontend bundle..."
    (cd frontend && npm ci && npm run build)
  else
    echo "Warning: npm not installed and frontend/dist/index.html missing. Build frontend on your dev machine or install Node 20+ and run 'cd frontend && npm ci && npm run build'." >&2
  fi
fi

mkdir -p workspace

API_PORT="${API_PORT:-8000}"

echo "==> Creating /etc/telugu-digitizer/env (if missing) and provisioning PostgreSQL..."
sudo mkdir -p /etc/telugu-digitizer
if [[ ! -f /etc/telugu-digitizer/env ]]; then
  DB_PASS="$(openssl rand -hex 18)"
  sudo tee /etc/telugu-digitizer/env >/dev/null <<EOF
DATABASE_URL=postgresql+psycopg://telugu_digitizer:${DB_PASS}@127.0.0.1:5432/telugu_digitizer
WORKSPACE_DIR=${REPO_DIR}/workspace
TESSDATA_DIR=${REPO_DIR}/models/tesseract/tessdata
API_HOST=127.0.0.1
API_PORT=${API_PORT}
PROXY_HEADERS=true
FORWARDED_ALLOW_IPS=127.0.0.1
CORS_ALLOWED_ORIGINS=https://lahari.org,https://www.lahari.org
ENABLE_PADDLE_OCR=${WITH_PADDLE}
OMP_NUM_THREADS=2
OPENBLAS_NUM_THREADS=2
MKL_NUM_THREADS=2
MAX_UPLOAD_MB=200
MAX_PDF_PAGES=1000
EOF
  sudo chmod 600 /etc/telugu-digitizer/env
  echo "Created open (no-login) environment config in /etc/telugu-digitizer/env (port ${API_PORT})"

  sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'telugu_digitizer') THEN
    CREATE ROLE telugu_digitizer WITH LOGIN PASSWORD '${DB_PASS}';
  END IF;
END \$\$;
SQL
  sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='telugu_digitizer'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE telugu_digitizer OWNER telugu_digitizer;"
fi

echo "==> Running Alembic database migrations..."
sudo bash -c "set -a; source /etc/telugu-digitizer/env; set +a; '${REPO_DIR}/.venv/bin/alembic' upgrade head"

echo "==> Installing systemd unit telugu-digitizer.service..."
RUN_USER="$(whoami)"
sed -e "s|__APP_USER__|${RUN_USER}|g" -e "s|__REPO_DIR__|${REPO_DIR}|g" \
  deploy/raspberry-pi/telugu-digitizer.service | sudo tee /etc/systemd/system/telugu-digitizer.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable telugu-digitizer.service
sudo systemctl restart telugu-digitizer.service

echo ""
echo "Setup complete! Local API/UI active on http://127.0.0.1:${API_PORT} (open access, no login)."
if command -v apache2ctl >/dev/null 2>&1 || [[ -x /usr/sbin/apache2ctl ]]; then
  echo "Detected Apache2. Proxy /telugu/ -> http://127.0.0.1:${API_PORT}/ inside your lahari.org VirtualHost."
elif command -v caddy >/dev/null 2>&1; then
  echo "Detected existing Caddy. Add or verify 'deploy/Caddyfile.direct' (UPSTREAM_ADDR=127.0.0.1:${API_PORT}) in your Caddy config for https://lahari.org."
elif command -v nginx >/dev/null 2>&1; then
  echo "Detected existing Nginx. Proxy https://lahari.org to http://127.0.0.1:${API_PORT} with 'client_max_body_size 250M;'."
else
  echo "Next: install Caddy (sudo apt install -y caddy) and load deploy/Caddyfile.direct (UPSTREAM_ADDR=127.0.0.1:${API_PORT}) to serve https://lahari.org."
fi
