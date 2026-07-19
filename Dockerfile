FROM python:3.14-slim

WORKDIR /app

# ffmpeg provides both `ffmpeg` and `ffprobe`, used by the worker to extract
# metadata and generate thumbnails. It's in the shared image (rather than a
# worker-only image) to keep this project's single image simple.
RUN apt-get update \
    && apt-get install --no-install-recommends -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY alembic.ini ./
COPY migrations/ ./migrations/
COPY src/ ./src/

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "video_processing.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
