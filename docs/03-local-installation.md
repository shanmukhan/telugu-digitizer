# 03 — Local Installation and Environment Setup

## 1. Recommended baseline environment

For the first repeatable PaddleOCR benchmark, use Ubuntu x86_64 on CPU. Python 3.11 or 3.12 is the preferred starting point; use a clean virtual environment. Do not reuse a Conda environment that already contains conflicting Torch/Paddle packages.

The user's Mac mini can run Tesseract and the web application locally. Native PaddlePaddle support must be checked against the current official platform wheel matrix before assuming it works on Apple Silicon. The primary benchmark environment should be one fixed supported host.

## 2. Ubuntu preparation

```bash
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-pip \
  git curl wget \
  tesseract-ocr \
  libgl1 libglib2.0-0 \
  fonts-noto-core

python3 --version
tesseract --version
```

If `fonts-noto-core` does not provide the required Telugu font files in a particular Ubuntu release, install the corresponding Noto Telugu package available in that release, then verify with `fc-list | grep -i telugu`.

## 3. Create the Python environment

```bash
mkdir -p ~/projects/telugu-book-digitizer
cd ~/projects/telugu-book-digitizer

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

Record the exact Python version:

```bash
python --version
python -c "import platform; print(platform.platform())"
```

## 4. Install PaddlePaddle CPU and PaddleOCR

The official PaddleOCR installation guide currently shows this CPU framework installation command:

```bash
python -m pip install paddlepaddle==3.2.0 \
  -i https://www.paddlepaddle.org.cn/packages/stable/cpu/

python -m pip install paddleocr
```

Verify:

```bash
python -c "import paddle; print('PaddlePaddle:', paddle.__version__)"
python -c "import paddleocr; print('PaddleOCR import: OK')"
```

If these exact wheels are unavailable for the selected Python/platform combination, do not force-install random wheels. Use the official PaddlePaddle installation selector and choose the matching OS, architecture, Python and CPU/GPU combination: https://www.paddlepaddle.org.cn/install/standalone

The current PaddleOCR documentation separates the `paddleocr` package from its inference engine; installing `paddleocr` alone is not sufficient for PaddlePaddle inference. References:

- https://www.paddleocr.ai/latest/en/version3.x/installation.html
- https://www.paddleocr.ai/latest/en/version3.x/paddlepaddle_installation.html

## 5. Install common application and benchmark libraries

```bash
python -m pip install \
  pymupdf \
  opencv-python-headless \
  pillow \
  numpy \
  regex \
  pandas \
  jiwer \
  python-docx \
  fastapi \
  uvicorn[standard] \
  pydantic \
  sqlalchemy \
  psycopg[binary] \
  alembic \
  pytest
```

For Phase 1, FastAPI and database dependencies can be installed but are not required by the command-line benchmark. Avoid `paddleocr[all]`; the general OCR pipeline does not require every optional PaddleOCR capability.

## 6. Install Tesseract Telugu best model

Create a project-local traineddata directory:

```bash
mkdir -p models/tesseract/tessdata
curl -L \
  https://github.com/tesseract-ocr/tessdata_best/raw/main/tel.traineddata \
  -o models/tesseract/tessdata/tel.traineddata
```

Check that the model exists:

```bash
ls -lh models/tesseract/tessdata/tel.traineddata
```

Run a test on a PNG page:

```bash
tesseract data/sample/page-0001.png stdout \
  -l tel --oem 1 --psm 6 \
  --tessdata-dir models/tesseract/tessdata
```

If the system Tesseract version is too old, follow the official Tesseract installation instructions for the OS rather than changing the traineddata file at random.

## 7. PaddleOCR smoke test

Create `scripts/paddle_smoke_test.py`:

```python
from pathlib import Path
from paddleocr import PaddleOCR

image = Path("data/sample/page-0001.png")
if not image.exists():
    raise SystemExit(f"Missing input image: {image}")

ocr = PaddleOCR(
    lang="te",
    ocr_version="PP-OCRv5",
    device="cpu",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)

results = ocr.predict(str(image))
Path("artifacts/paddle").mkdir(parents=True, exist_ok=True)
for index, result in enumerate(results, start=1):
    result.print()
    result.save_to_json(save_path=f"artifacts/paddle/page-0001-{index}")
```

Run:

```bash
python scripts/paddle_smoke_test.py
```

The first invocation downloads pretrained model files if they are not cached. After the model files are present, verify the OCR process with the network disconnected. If it tries to download a model again, the local model cache/configuration is not yet self-contained.

## 8. macOS Apple Silicon notes

For the Mac mini, install Tesseract with Homebrew:

```bash
brew update
brew install tesseract
brew install --cask font-noto-sans-telugu font-noto-serif-telugu

tesseract --version
tesseract --list-langs
```

If `tel` is not listed, download `tel.traineddata` from the official `tessdata_best` repository and pass a project-local `--tessdata-dir` as shown above.

Do not assume the `paddlepaddle` CPU wheel exists for the current macOS/ARM64/Python version. Check the official wheel selector and test installation in a clean environment. If unavailable, keep PaddleOCR on the Ubuntu x86_64 local machine and use Tesseract on the Mac. Both are local processing options; neither requires uploading book content to a cloud OCR API.

## 9. Capture a reproducibility manifest

After successful installation:

```bash
python -m pip freeze > requirements-phase1.lock.txt
python - <<'PY'
import platform, sys
print("Python:", sys.version)
print("Platform:", platform.platform())
try:
    import paddle
    print("PaddlePaddle:", paddle.__version__)
except Exception as exc:
    print("PaddlePaddle unavailable:", repr(exc))
try:
    import paddleocr
    print("PaddleOCR module:", getattr(paddleocr, "__version__", "version attribute unavailable"))
except Exception as exc:
    print("PaddleOCR unavailable:", repr(exc))
PY
```

Also record `tesseract --version` and SHA-256 hashes of downloaded model files. Save this manifest beside each benchmark report.

## 10. Troubleshooting rules

- Keep one clean virtual environment per OCR stack if dependency conflicts appear.
- Do not install both CPU and GPU PaddlePaddle distributions in one environment.
- Do not install a CUDA runtime just because `nvidia-smi` reports a CUDA compatibility version; follow Paddle's driver/runtime wheel matrix.
- If PaddleOCR uses a non-Telugu model, inspect the initialization config and confirm `lang="te"` and `ocr_version="PP-OCRv5"`.
- If Tesseract says `Failed loading language 'tel'`, check `tel.traineddata` exists in the exact `--tessdata-dir` used by the command.
