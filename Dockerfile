# ClippyMe — Multi-platform Dockerfile
#
# CPU / Apple Silicon (default):  docker compose up --build
# NVIDIA GPU:                     docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build

ARG GPU_RUNTIME=cpu

# ============================================================
# Stage 2a: NVIDIA CUDA runtime (x86_64 only)
# ============================================================
FROM nvidia/cuda:12.3.2-cudnn9-runtime-ubuntu22.04 AS runtime-nvidia

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev python3.11-distutils \
    ffmpeg libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    curl unzip ca-certificates && \
    curl -fsSL https://deno.land/install.sh | sh && \
    mv /root/.deno/bin/deno /usr/local/bin/ && \
    rm -rf /root/.deno && \
    ln -sf /usr/bin/python3.11 /usr/bin/python && \
    ln -sf /usr/bin/python3.11 /usr/bin/python3 && \
    curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 && \
    rm -rf /var/lib/apt/lists/*

ENV NVIDIA_VISIBLE_DEVICES=all
ENV NVIDIA_DRIVER_CAPABILITIES=compute,utility

# ============================================================
# Stage 2b: CPU runtime (multi-arch: amd64, arm64, Apple Silicon)
# ============================================================
FROM python:3.11-slim AS runtime-cpu

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ffmpeg libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    curl unzip ca-certificates && \
    curl -fsSL https://deno.land/install.sh | sh && \
    mv /root/.deno/bin/deno /usr/local/bin/ && \
    rm -rf /root/.deno && \
    rm -rf /var/lib/apt/lists/*

# ============================================================
# Stage 3: Final image
# ============================================================
FROM runtime-${GPU_RUNTIME} AS final

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Install Python deps. CUDA pip wheels (nvidia-cublas-cu12, cudnn) are only
# needed on the GPU path — skipping them on CPU saves ~500 MB per image.
ARG GPU_RUNTIME
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    if [ "$GPU_RUNTIME" = "nvidia" ]; then \
        pip install --no-cache-dir nvidia-cublas-cu12 && \
        SITE=$(python -c "import site; print(site.getsitepackages()[0])") && \
        echo "$SITE/nvidia/cublas/lib" > /etc/ld.so.conf.d/nvidia-pip.conf && \
        echo "$SITE/nvidia/cudnn/lib" >> /etc/ld.so.conf.d/nvidia-pip.conf && \
        ldconfig 2>/dev/null || true; \
    fi && \
    pip install --upgrade --no-cache-dir yt-dlp

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser && \
    mkdir -p /app/uploads /app/output /app/data /tmp/Ultralytics && \
    chown -R appuser:appuser /app /tmp/Ultralytics

USER appuser

# Pre-download YOLO model
RUN python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"

COPY --chown=appuser:appuser . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl http://localhost:8000/ || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
