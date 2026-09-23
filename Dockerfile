# The assistant as a single container: Python, Tesseract, the embedding model
# and the app, ready to run on any machine that has Docker.
#
# Build:  docker compose build
# Run:    docker compose up -d
#
# Two decisions worth knowing about:
#
#   * PyTorch is installed from the CPU-only index. The default wheels carry
#     NVIDIA GPU libraries and add several gigabytes to an image that will never
#     see a GPU in a back office.
#   * The embedding model is downloaded at build time. The container then starts
#     instantly and works with no internet connection at all - which is the
#     answer to "does our data leave the building?" for everything except the
#     final answer-writing step.

FROM python:3.12-slim

# Tesseract reads the scanned documents. `--no-install-recommends` keeps the
# image small; the eng language data is the only one we need.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng \
        curl \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/models \
    ANONYMIZED_TELEMETRY=False

WORKDIR /app

# Dependencies first, so editing the code later rebuilds in seconds rather than
# re-downloading everything.
COPY requirements.txt .
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image (about 130 MB).
RUN python -c "from sentence_transformers import SentenceTransformer; \
               SentenceTransformer('BAAI/bge-small-en-v1.5')"

COPY app ./app
COPY static ./static
COPY scripts ./scripts
COPY eval ./eval
COPY sample_data ./sample_data

# The app runs as an ordinary user, not root: if anything ever goes wrong with
# an uploaded file, it should not be running with full rights.
RUN useradd --create-home --uid 1000 assistant \
    && mkdir -p /app/documents /app/index \
    && chown -R assistant:assistant /app /opt/models
USER assistant

EXPOSE 8000

# Docker restarts the container if this stops answering.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fs http://localhost:8000/api/status || exit 1

CMD ["uvicorn", "app.web:api", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]
