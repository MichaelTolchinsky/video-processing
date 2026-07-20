# AGENTS.md

Instructions for AI coding agents working in this repository. This is not a second README (see [`readme.md`](readme.md) for the human-facing project overview) -- it only covers what an agent can't infer from the code itself: exact commands, boundaries, and conventions.

## Project

Video upload/processing platform: FastAPI API + a separate async worker, on AWS ECS/Fargate, deployed with CDK. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full design.

## Stack

- Python >=3.12 (`pyproject.toml`); the Docker image runs 3.14. `uv` for dependency management (not pip/poetry directly)
- FastAPI + Pydantic v2 (API), SQLAlchemy 2.0 + Alembic (DB), boto3 (S3/SQS), `psycopg` (Postgres driver)
- PostgreSQL 16 (RDS in AWS, `postgres:16` locally), LocalStack (S3+SQS) for local dev, Docker Compose
- `ffmpeg`/`ffprobe` (installed in the image) for the worker's video processing
- AWS CDK (Python) for infrastructure; GitHub Actions for CI/CD
- `ruff` for lint (see Commands) -- no other formatter/type-checker is configured

## Commands

```bash
# Lint (run before considering any Python change done)
uv run ruff check .
uv run ruff check --fix .      # auto-fix what's safe to auto-fix

# Local stack (API + worker + Postgres + LocalStack)
docker compose up --build
docker compose logs -f worker  # or api

# Apply/create migrations (see Boundaries -- review before applying, always)
docker compose run --rm -v "$PWD:/workspace" -w /workspace api alembic upgrade head
docker compose run --rm -v "$PWD:/workspace" -w /workspace api alembic revision --autogenerate -m "describe the change"

# Infra (from infra/, its own venv/dependencies)
cd infra && .venv/bin/python app.py    # synthesize/validate
npx cdk diff ServicesStack             # preview a change
```

Full end-to-end local test steps (create upload, upload a file, watch the worker, verify assets): see [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).

## Project Structure

```text
src/video_processing/
├── api/            # FastAPI app -- routes/, schemas/ (Pydantic request/response only)
├── worker/         # SQS poll loop: s3_events.py (parse), processing.py (ffprobe/thumbnail),
│                   # transcode.py (resolution renditions), jobs.py (DB claim/complete/fail), main.py (orchestration)
└── common/         # Shared by api/ AND worker/ only: config/, db/, models/, queue/, storage/
migrations/         # Alembic; versions/ is generated, excluded from ruff
infra/              # AWS CDK app (separate venv/dependencies from the app itself)
```

`api/` and `worker/` never import from each other -- if both need something, it belongs in `common/`, not copied into both.

## Testing

**No automated test suite exists in this repository.** `ruff check .` is the only automated gate. Do not add a test suite or testing framework without confirming scope first (see Boundaries); a clean lint run is the current bar for "done," not a substitute for reasoning through correctness.

## Code Style

Apply KISS, DRY, and SOLID pragmatically -- match the existing code's style even where you'd personally do it differently, and flag an inconsistency instead of introducing a second style.

### KISS -- the simplest thing that solves the actual problem

**Good** -- the worker's poll loop is a plain `while True` calling `receive_message`/`delete_message`; no framework, no abstraction layer, because that's all a long-poll consumer needs:

```python
def run() -> None:
    sqs = get_sqs_client()
    while True:
        response = sqs.receive_message(QueueUrl=settings.sqs_queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=20)
        for message in response.get("Messages", []):
            ...
```

**Bad** -- wrapping that in a `WorkerRunner` class with a `Strategy` interface for message processing when there is exactly one strategy and one caller.

### DRY -- only for *real* duplication

**Good** -- every enum column needs identical SQLAlchemy configuration (lowercase string values, CHECK constraint), so it's centralized once in `common/models/enum_type.py` and reused by every model:

```python
status: Mapped[VideoStatus] = mapped_column(enum_type(VideoStatus), default=VideoStatus.PENDING_UPLOAD)
```

**Bad** -- copy-pasting the `Enum(..., native_enum=False, create_constraint=True, values_callable=...)` block into every model file.

**Also bad** -- the opposite failure: inventing a shared abstraction after seeing a pattern *once*. Two similar lines aren't duplication yet.

### Single Responsibility -- split by concern, not by layer buzzwords

**Good** -- the worker is split into `main.py` (orchestration only), `s3_events.py` (parsing), `processing.py` (ffprobe/thumbnail), `transcode.py` (resolution renditions), `jobs.py` (DB claim/complete/fail) -- each file is understandable on its own, and a change to "how we parse S3 events" never touches ffmpeg code. Within `main.py` itself, each job's work is a separate `_run_*_job` helper so the top-level function reads as an orchestration summary, not 100 lines of inline logic.

**Bad** -- one function that downloads, probes, thumbnails, transcodes, and writes to the DB inline, so understanding "how does retry work" requires reading unrelated ffmpeg argument lists first.

### Open/closed -- extend via new modules/enum values, not by rewriting shared logic

**Good** -- `JobType`/`AssetType` are enums specifically so a new processing step is a new enum value plus a new worker module, not a rewrite of `claim_job`/`complete_*_job`. Those functions take a `job_type` parameter, so adding a job type is a pure extension:

```python
def claim_job(db: Session, video: Video, job_type: JobType) -> ProcessingJob | None: ...
```

**Bad** -- hardcoding a single job type inside `claim_job` and branching on it internally as job types grow, instead of parameterizing.

### Don't force interfaces where there's one implementation

**Good** -- `common/storage/s3.py` is plain functions (`get_s3_client()`, `get_presigning_s3_client()`), not a `StorageClient` abstract base class. There is exactly one backing implementation (boto3 + real/LocalStack S3); no repository-pattern interface layer either, for the same reason -- SQLAlchemy is the only persistence mechanism this project has or plans to have.

**Bad** -- introducing an interface "in case we swap databases/storage later" with no concrete second implementation in sight.

### Idempotency and failure handling are part of the design

SQS delivers at-least-once, so "handle being called twice" isn't optional.

**Good** -- `claim_job` tolerates a duplicate/redelivered message by design: unique-constraint the first writer wins, `IntegrityError` on the loser falls back to reading the row instead of crashing, and an already-`completed` job is a no-op:

```python
try:
    db.commit()
except IntegrityError:
    db.rollback()
    job = _get_job(db, video, job_type)

if job.status == JobStatus.COMPLETED:
    return None
```

**Bad** -- catching and swallowing an exception during processing without re-raising. In this worker, that would delete the SQS message on a failed job, silently losing the video with no retry and no DLQ entry.

**Watch for autoflush pitfalls when using a session configured with `autoflush=False`** (as this project's `SessionFactory` is): a query that depends on an attribute set earlier in the same transaction will not see that change until it is flushed. Completion checks that run a `SELECT` immediately after updating an in-memory attribute (e.g. counting completed jobs right after setting `job.status = COMPLETED`) need an explicit `db.flush()` first, or they will read stale data.

### Least privilege by default (infra)

**Good** -- the worker's ECS task role grants exactly `s3:GetObject` on `uploads/*` and `s3:PutObject` on `assets/*` -- nothing else, scoped to the prefixes it actually touches.

**Bad** -- a blanket `bucket.grant_read_write()` because it's less code to write.

### Comments: explain *why*, not *what*

**Good**:

```python
# LocalStack (as of 3.8.1) stores presigned-PUT uploads with a literal
# trailing backslash on the key; real AWS S3 never does this.
```

**Bad**:

```python
# Increment attempts by 1
job.attempts += 1
```

If removing a comment loses no information, delete the comment, not the code.

### Type hints

Full type hints on function signatures and SQLAlchemy `Mapped[...]` columns, everywhere -- treat a missing type hint on a new function as a gap to fill, not a style nit to skip.

## Migrations

Migrations are generated (`alembic revision --autogenerate`), never hand-written from scratch -- but **always reviewed by hand before applying**, not blindly accepted. `migrations/env.py` imports every model explicitly so it registers on `Base.metadata`; a new model must be added there too.

This project's enum columns (`common/models/enum_type.py`, `create_constraint=True`) use anonymous CHECK constraints, not native Postgres enum types -- and Alembic's autogenerate is unreliable for these specifically. When an enum gains/loses values, autogenerate tends to emit a same-named `ADD CONSTRAINT` without dropping the old one first (fails outright), and never adds a data-fix for rows still holding a removed value (which a real `ADD CONSTRAINT` would then reject). Expect to hand-write `op.drop_constraint(...)` / `op.create_check_constraint(...)`, and an `op.execute("UPDATE ...")` data-fix if a value was renamed/removed.

## Git Workflow

- Feature branches, prefixed by the developer's name (e.g. `<name>-<feature>`).
- Commits and PRs merge into `main`.
- Alembic migration files, `alembic.ini`, and `migrations/env.py`/`script.py.mako` are committed; `migrations/versions/*` files are committed once reviewed (see Migrations above).

## Boundaries

- ✅ **Always do:** run `ruff check .` before considering a Python change done; review every migration by hand before applying it; keep `api/` and `worker/` free of imports from each other.
- ⚠️ **Ask first:** running or rebuilding Docker containers (`docker compose up`, `run`, etc.) -- don't start/stop/rebuild them unprompted; adding a test suite or new test framework; adding new runtime dependencies, especially large ones (e.g. ML/GPU libraries) that meaningfully shift the project's scope or resource footprint; changing AWS-deployed resource names (renaming an ECS service/cluster/task-definition family causes CloudFormation to replace it, which is a real, if brief, production interruption, not just a diff).
- 🚫 **Never do:** commit secrets, AWS account IDs, or `.env` files (`infra/cdk.context.json` is gitignored for this reason -- it's a regenerable cache, not config); hand-write a migration from scratch instead of autogenerating + correcting; reformat/hand-edit `migrations/versions/*.py` beyond what a migration actually needs (they're excluded from ruff on purpose); add a repository-pattern/interface abstraction for something with a single implementation.
