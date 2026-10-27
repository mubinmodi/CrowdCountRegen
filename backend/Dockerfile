# syntax=docker/dockerfile:1
FROM python:3.12-slim

# libGL/glib for OpenCV, ffmpeg libs come bundled with the opencv wheel.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.13 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

WORKDIR /app

# Which detector backends to install: "yolo", "rfdetr", or "yolo rfdetr".
ARG DETECTOR_EXTRAS="yolo"
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project $(for e in $DETECTOR_EXTRAS; do printf -- "--extra %s " "$e"; done)

COPY app ./app
RUN useradd --create-home app && mkdir -p /data /app/models && chown -R app /data /app/models
USER app

ENV CC_DATABASE_URL=sqlite:////data/crowdcounting.db \
    PATH="/app/.venv/bin:$PATH"
VOLUME ["/data", "/app/models"]
EXPOSE 8000
# Live streams never finish on their own, so bound the graceful shutdown.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--timeout-graceful-shutdown", "3"]
