# 13 — Raspberry Pi Deployment & Hosting on `lahari.org`

Complete guide to running **Telugu Book Digitizer** natively on a **Raspberry Pi (64-bit `aarch64`, no Docker required)** and publishing it openly over HTTPS at **`https://lahari.org/telugu/`** alongside the existing apps on `lahari.org`.

---

## 1. Do We Need Docker?

**No.** Docker is completely optional. Installing natively with Python `.venv`, PostgreSQL, Tesseract, `systemd`, and Apache/Caddy avoids container memory/overlay overhead on Raspberry Pi and gives direct access to your storage.

---

## 2. Hardware & OS Prerequisites

- **Hardware:** Raspberry Pi 5 (8 GB RAM recommended for dual PaddleOCR + Tesseract) or Raspberry Pi 4 (4–8 GB; use `--tesseract-only` on 2–4 GB boards).
- **Storage:** Boot/run from an **NVMe / USB 3.0 SSD** rather than a microSD card (PostgreSQL + 300-DPI PNG page images write heavily).
- **OS:** 64-bit **Raspberry Pi OS / Debian Bookworm or Trixie (`aarch64`)** or **Ubuntu Server 24.04 ARM64**. Verify `uname -m` returns `aarch64`. (`install.sh` automatically selects `libglib2.0-0t64` on Trixie or `libglib2.0-0` on Bookworm.)
- **OCR Engines on `linux_aarch64`:**
  - **Tesseract 5 (`tel.traineddata` from `tessdata_best`)** runs natively and quickly.
  - **PaddlePaddle `3.3.1`** provides official `linux_aarch64` CPU wheels including Python 3.13 (`cp313-linux_aarch64`) at `https://www.paddlepaddle.org.cn/packages/stable/cpu/`. On lower-RAM Pis (`<= 4 GB`), pass `--tesseract-only` to `install.sh` (sets `ENABLE_PADDLE_OCR=false`).

---

## 3. Public Access Mode (Open / No Login Page)

By default in native `install.sh` and `.env.lahari.example`, **`APP_AUTH_USERNAME` and `APP_AUTH_PASSWORD` are unset**, so anyone visiting `https://lahari.org` can use the studio immediately with **no login page**.

*(Optional abuse note: because uploads/OCR/deletes are open to the public without authentication, monitor disk space under `workspace/` and back up important data regularly. HTTP Basic Auth remains available optionally via `APP_AUTH_USERNAME` / `APP_AUTH_PASSWORD` if ever needed later.)*

---

## 4. Option A (Recommended): Native Raspberry Pi OS Install (No Docker)

### Step 1 — Push code from your Mac to the Pi (if deploying remotely)

```sh
./deploy/raspberry-pi/remote-deploy.sh lipi@192.168.1.13 --mode native --with-paddle --port 8085
# Or on lower-RAM Pis:
# ./deploy/raspberry-pi/remote-deploy.sh <user@pi-host> --mode native --tesseract-only --port 8085
```

Or directly on the Pi:

```sh
git clone https://github.com/shanmukhan/telugu-digitizer.git
cd telugu-digitizer
API_PORT=8085 ./deploy/raspberry-pi/install.sh --with-paddle
```

`install.sh` sets up PostgreSQL (`telugu_digitizer`), `.venv`, OCR models, `alembic upgrade head`, open-access `/etc/telugu-digitizer/env`, and `systemd` service `telugu-digitizer.service` on `127.0.0.1:8085` (avoiding `127.0.0.1:8000` already used by `rpi-monitor`).

### Step 2 — Serve HTTPS on `https://lahari.org/telugu/` (Apache2 on Pi — or Caddy/Nginx)

Because `lahari.org` already serves the main hub (`/`), Science Lab (`/lab/`), visitor counter (`/api/`), RPi Monitor (`/monitor/`), and trading tools via Apache2 (`/etc/apache2/sites-available/lahari.org.conf`, managed by `~/Developer/repo/rpi-setup`), the frontend builds with relative assets (`base: "./"`) and relative API resolution (`resolveAppUrl()`) so it works identically at `/` or `/telugu/`:

- **With existing Apache2 (live setup on `192.168.1.13`):**
  - `rpi-setup/scripts/apache-templates/lahari.org.conf.tmpl` (`configure-lahari.sh`, `__TELUGU_DIGITIZER_PORT__=8085`) adds `RedirectMatch 302 "^/telugu$" "/telugu/"` and `<Location /telugu/>` (`ProxyPass http://127.0.0.1:8085/`, `LimitRequestBody 262144000`, `timeout=300`) inside `<VirtualHost *:443>`, keeping `/`, `/lab/`, `/api/`, `/monitor/`, and `trading-apps.conf` intact.
  - `rpi-setup/scripts/site-content/lahari-home/index.html` links directly to `/telugu/` in the top navigation bar and Product Card `07` (`Telugu Digitizer`).
- **Live verified (2026-11-24 on `lipi@192.168.1.13`, Debian 13 `trixie` `aarch64`, Python `3.13.5`):**
  - `telugu-digitizer.service` active on `127.0.0.1:8085`; PostgreSQL `17` migrations (`0001_initial_schema` → `0002_exports_table`) applied.
  - Public HTTPS checks passing: `https://lahari.org/` (`200`), `/lab/` (`200`), `/api/visits/stats` (`200`), `/monitor/health` (`200`), `/agentic-trader/workspace` (`200`), `/portfolio-advisor/` (`401`), `/telugu` (`302` → `/telugu/`), `/telugu/` (`200`), `/telugu/assets/index-*.js` / `.css` / `pdf.worker.min-*.mjs` (`200`), `/telugu/api/v1/health` (`200`), `/telugu/api/v1/capabilities` (`200` with both `paddle_ppocrv5_te` and `tesseract_tel_best` enabled and `auth_enabled: false`), and `/telugu/api/v1/books` (`200`).
- **Or on a standalone Caddy/Nginx host:** set `UPSTREAM_ADDR=127.0.0.1:8085` with `deploy/Caddyfile.direct` (`max_size 250MB`), Nginx (`client_max_body_size 250M;`), or Cloudflare Tunnel (`deploy/raspberry-pi/cloudflared-config.yml.example` + `deploy/Caddyfile.tunnel`).

---

## 5. Option B (Optional): Docker Compose

If you prefer containers, `deploy/compose.lahari.yml` + `deploy/Dockerfile` remain available:

```sh
cp deploy/.env.lahari.example deploy/.env.lahari
nano deploy/.env.lahari
docker compose -f deploy/compose.lahari.yml --env-file deploy/.env.lahari up -d --build
```

---

## 6. Operations & Backups

```sh
# Check live service status and logs (native systemd install)
sudo systemctl status telugu-digitizer
sudo journalctl -u telugu-digitizer -f

# Back up PostgreSQL & workspace files
pg_dump -U telugu_digitizer -h 127.0.0.1 telugu_digitizer > backup_$(date +%F).sql
rsync -av workspace/ /mnt/backup/telugu-digitizer-workspace/
```
