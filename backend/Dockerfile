FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install ffmpeg and Deno (for yt-dlp YouTube JS signature challenges)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    unzip \
    ca-certificates \
  && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py downloader.py app.py ./

RUN useradd --create-home --uid 1000 appuser \
  && mkdir -p /app/downloads \
  && chown -R appuser:appuser /app

USER appuser

ENV HOST=0.0.0.0 \
    PORT=8000 \
    DOWNLOAD_DIR=/app/downloads

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}"]
