FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DND_TRACKER_DATA=/data

WORKDIR /app
COPY requirements.txt .
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static
COPY data/catalog.json ./data/catalog.json
COPY VERSION CHANGELOG.md ./
RUN python -m app.version --check

# Run as an unprivileged user. Match PUID/PGID to the owner of the data folder on the host.
ARG PUID=1000
ARG PGID=1000
RUN groupadd -g ${PGID} tracker && useradd -u ${PUID} -g ${PGID} -M -s /usr/sbin/nologin tracker \
    && mkdir -p /data /pdfs && chown tracker:tracker /data
USER tracker

VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/meta')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
