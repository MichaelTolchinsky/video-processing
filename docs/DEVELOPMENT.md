# Local Development

Full local setup and commands for this project. See [`readme.md`](../readme.md) for the project overview and [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) for design details.

Everything runs in Docker Compose — API, worker, PostgreSQL, and a LocalStack container standing in for S3 + SQS. No AWS account or credentials are needed for local development.

## Prerequisites

- Docker and Docker Compose
- `curl` (or Postman) for exercising the API
- A small local `.mp4` file to upload for testing

## Start the stack

```bash
docker compose up --build
```

This starts:

- `api` — FastAPI on `http://localhost:8000`
- `worker` — the SQS poll loop (no exposed port)
- `db` — PostgreSQL 16 on `localhost:5432`
- `localstack` — S3 + SQS on `http://localhost:4566`, with the `video-processing-local` bucket and queue created automatically (see `localstack/init-s3.sh` and `localstack/init-sqs.sh`), including the bucket's `uploads/` → queue notification wiring that mirrors production.

## Run the test suite

Unit and integration tests run against an in-memory SQLite database and mocked S3 calls — no Docker/AWS needed:

```bash
uv run pytest
```

Covers repositories (`common/db/repositories/`), worker job idempotency/retry logic (`worker/jobs.py`), the API service layer, and HTTP-level route behavior (via FastAPI's `TestClient`). It does not replace the [end-to-end test](#end-to-end-test) below, which is the only check that exercises real ffmpeg/ffprobe and the full worker poll loop.

## Apply database migrations

The API image doesn't run migrations on startup by design (so a bad migration can't block every container from starting). Run them explicitly:

```bash
docker compose run --rm -v "$PWD:/workspace" -w /workspace api alembic upgrade head
```

The `-v`/`-w` flags mount the project root, since the built image's default `/app` only contains the installed package, not the Alembic project files.

Create a new migration after changing a model:

```bash
docker compose run --rm -v "$PWD:/workspace" -w /workspace api alembic revision --autogenerate -m "describe the change"
```

Always review the generated migration file before applying it -- autogenerate is known to be unreliable specifically for the enum columns in this project (`common/models/enum_type.py` uses `create_constraint=True`, an anonymous CHECK constraint, not a native Postgres enum). When an enum gains/loses values, autogenerate tends to emit a same-named `ADD CONSTRAINT` without dropping the old one first, which fails outright; it also won't add a data-fix for rows still holding a removed value, which a straight `ADD CONSTRAINT` would otherwise reject. Expect to hand-write explicit `op.drop_constraint(...)` / `op.create_check_constraint(...)` (and an `op.execute("UPDATE ...")` data-fix if a value was renamed/removed) rather than accepting the generated file as-is.

## End-to-end test

**1. Create the upload record**

```bash
curl -X POST http://localhost:8000/videos -H 'Content-Type: application/json' -d '{"filename":"salmon.mp4","content_type":"video/mp4"}'
```

Copy `id` and `upload_url` from the response.

**2. Upload the file directly to S3**

```bash
curl -X PUT --upload-file ./salmon.mp4 -H 'Content-Type: video/mp4' 'PASTE_UPLOAD_URL_HERE'
```

This is what triggers the S3 → SQS event the worker consumes.

**3. Watch the worker process it**

```bash
docker compose logs -f worker
```

Expect a "Completed processing for video ..." line within a few seconds.

**4. Check the result**

```bash
curl http://localhost:8000/videos/PASTE_VIDEO_ID
```

Expect `status: "completed"`, populated `metadata`, and generated assets: `thumbnail`, plus a `preview_{height}p` rendition for each standard resolution (1080p/720p/480p) strictly below the source's height -- e.g. a 1080p source produces `preview_720p` and `preview_480p` but not a redundant `preview_1080p`. Each asset has a working `download_url`.

**5. Inspect LocalStack directly (optional)**

```bash
# List uploaded originals
docker compose exec localstack awslocal s3 ls s3://video-processing-local/uploads/ --recursive

# List generated assets
docker compose exec localstack awslocal s3 ls s3://video-processing-local/assets/ --recursive

# Peek at a queue message without consuming it (useful when debugging the worker)
docker compose exec localstack awslocal sqs receive-message \
  --queue-url http://localhost:4566/000000000000/video-processing-local \
  --max-number-of-messages 1 --visibility-timeout 3600
```

## Everyday commands

```bash
# Rebuild after a dependency change (pyproject.toml / uv.lock)
docker compose up --build

# Follow logs for one service
docker compose logs -f api
docker compose logs -f worker

# Restart just one service after a code change (api/worker source is bind-mounted,
# so most changes don't need a rebuild — api runs with --reload; worker needs a restart)
docker compose restart worker

# Stop everything (keeps the postgres_data volume)
docker compose down

# Stop and wipe the database too (fresh start)
docker compose down -v
```

## Managing Python dependencies

Dependencies are managed with `uv` and locked in `uv.lock`:

```bash
uv add <package>       # add a runtime dependency
uv sync                # install/update the local .venv from the lockfile
```

The root `.venv` is for editor/IDE support only (import resolution, linting) — the application itself always runs inside Docker. `infra/.venv` is separate and only used for CDK commands.
