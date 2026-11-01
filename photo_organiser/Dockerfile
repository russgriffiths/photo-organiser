FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends libimage-exiftool-perl curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PHOTOS_ROOT=/photos \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1

EXPOSE 5000

HEALTHCHECK --interval=60s --timeout=10s --start-period=30s \
    CMD curl -fsS http://localhost:5000/health || exit 1

# One worker: the scheduler and the run lock live in this process.
CMD ["gunicorn", "--workers", "1", "--threads", "4", "--timeout", "120", "-b", "0.0.0.0:5000", "app:create_app()"]
