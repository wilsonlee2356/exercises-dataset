# reelgen — form-check reel generator (web UI + CLI)
# Build context is the REPO ROOT (needs data/, images/, videos/):
#   docker compose build reelgen        (see docker-compose.yml at repo root)
FROM python:3.11-slim

# DejaVu fonts: reelgen's card renderer falls back to these on Linux
# (see FONT_CANDIDATES_* in reelgen.py). ffmpeg comes from imageio-ffmpeg.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pillow imageio-ffmpeg

WORKDIR /app
COPY data/          /app/data/
COPY images/        /app/images/
COPY videos/        /app/videos/
COPY tools/reelgen/ /app/tools/reelgen/

EXPOSE 8321

# --host 0.0.0.0 is required for the host port mapping to reach the server.
CMD ["python", "tools/reelgen/server.py", "--host", "0.0.0.0", "--port", "8321", "--no-browser"]
