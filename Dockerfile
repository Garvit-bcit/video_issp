
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies once and keep the image small
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies separately so Docker can cache this layer
COPY requirements.txt .

# Reuse pip's download cache between builds
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy application code after dependencies
COPY . .

RUN mkdir -p /data/videos /data/reports

ENV DATA_DIR=/data \
    VIDEO_STORAGE=/data/videos \
    REPORT_STORAGE=/data/reports \
    PORT=5000

EXPOSE 5000

CMD ["gunicorn", "--workers", "1", "--threads", "4", "--timeout", "1800", "--bind", "0.0.0.0:5000", "app:app"]
