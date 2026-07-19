# AGENTS.md

Guidance for coding agents (and contributors) working in this repository. Optimized for writing efficient, maintainable Python — apply KISS, DRY, and SOLID pragmatically, not as boxes to check. When a rule below and the existing code around your change disagree, match the existing code and flag the inconsistency instead of introducing a second style.

## KISS — do the simplest thing that solves the actual problem

Prefer the smallest change that fully works over a more "flexible" one nobody asked for.

**Good** — the worker's poll loop is a plain `while True` calling `receive_message`/`delete_message`; no framework, no abstraction layer, because that's all a long-poll consumer needs:

```python
def run() -> None:
    sqs = get_sqs_client()
    while True:
        response = sqs.receive_message(QueueUrl=settings.sqs_queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=20)
        for message in response.get("Messages", []):
            ...
```

**Bad** — wrapping that in a `WorkerRunner` class with a `Strategy` interface for message processing when there is exactly one strategy and one caller. Don't build for a second implementation that doesn't exist yet.

## DRY — but only for *real* duplication

Extract shared logic once it's actually shared, not on the first occurrence.

**Good** — every enum column needs identical SQLAlchemy configuration (lowercase string values, check constraint), so it's centralized once in `common/models/enum_type.py` and reused by every model:

```python
status: Mapped[VideoStatus] = mapped_column(enum_type(VideoStatus), default=VideoStatus.PENDING_UPLOAD)
```

**Bad** — copy-pasting the `Enum(..., native_enum=False, create_constraint=True, values_callable=...)` block into every model file. The moment one of them drifts, you have two silently different enum behaviors.

**Also bad** — the opposite failure mode: inventing a shared "base config" abstraction after seeing the pattern *once*. Two similar-looking lines aren't duplication yet; three or more identical rules across models are.

## SOLID, applied practically (not academically)

- **Single Responsibility** — split by concern, not by layer buzzwords. The worker is `main.py` (orchestration), `s3_events.py` (parsing), `processing.py` (ffprobe/ffmpeg), `jobs.py` (DB claim/complete/fail) — each file is understandable on its own, and a change to "how we parse S3 events" never touches ffmpeg code.
- **Dependency direction** — `common/` holds everything both `api/` and `worker/` need (settings, DB session, models, S3/SQS clients); `api/` and `worker/` never import from each other. If two processes start needing the same non-trivial logic, it belongs in `common/`, not copied into both.
- **Open/closed in practice** — `JobType` and `AssetType` are enums specifically so a new processing job (e.g., an embeddings job — see `docs/ARCHITECTURE.md`) is a new enum value plus a new job module, not a rewrite of `claim_job`/`complete_job`.
- **Don't force interfaces where there's one implementation** — no `AbstractStorageClient` for a single `get_s3_client()`. Introduce an interface when a second real implementation shows up, not preemptively.

## Structure by responsibility

`common/` is organized by *what it does*:

```text
common/
├── config/    # Settings (pydantic-settings)
├── db/        # SQLAlchemy engine/session
├── models/    # SQLAlchemy entities + enums
├── queue/     # SQS client
└── storage/   # S3 clients
```

## Settings: one source of truth

**Good** — all configuration flows through one `Settings` instance:

```python
from video_processing.common.config.settings import settings
settings.s3_bucket_name
```

**Bad** — reaching for `os.environ["S3_BUCKET_NAME"]` in a route or worker module. It bypasses validation, defaults, and makes it impossible to see all configuration in one place.

## Models vs. schemas: don't blur the boundary

SQLAlchemy models (`common/models/`) are for persistence. Pydantic schemas (`api/schemas/`) are for the API request/response boundary. Keep them separate even when fields look identical today — they change for different reasons (a DB column rename shouldn't be an API breaking change, and vice versa).

**Bad**: returning a SQLAlchemy `Video` instance directly as a FastAPI `response_model`. It leaks internal columns and couples your API contract to your schema migrations.

## Idempotency and failure handling are part of the design, not an afterthought

SQS delivers at-least-once, so "handle being called twice" isn't optional.

**Good** — `claim_job` tolerates a duplicate/redelivered message by design: unique-constraint the first writer wins, `IntegrityError` on the loser falls back to reading the row instead of crashing, and an already-`completed` job is treated as a no-op:

```python
try:
    db.commit()
except IntegrityError:
    db.rollback()
    job = _get_job(db, video)

if job.status == JobStatus.COMPLETED:
    return None
```

**Bad** — catching and swallowing an exception during processing without re-raising. In this worker, that would delete the SQS message on a failed job, silently losing the video with no retry and no DLQ entry. Fail loudly enough that the caller (the poll loop) knows not to delete the message.

## Least privilege by default

**Good** — the worker's task role grants exactly `s3:GetObject` on `uploads/*` and `s3:PutObject` on `assets/*` — nothing else, and scoped to the prefixes it actually touches.

**Bad** — a blanket `bucket.grant_read_write()` because it's less code to write. It works, but it silently expands what a compromised task can do.

## Comments: explain *why*, not *what*

A comment should carry information the code can't — a non-obvious decision, trade-off, or gotcha.

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

## Migrations

Alembic migrations are generated (`alembic revision --autogenerate`), then reviewed by hand — never hand-written from scratch. `migrations/env.py` imports every model explicitly so it registers on `Base.metadata`; a new model must be added there too, or autogenerate silently won't see it.

## Type hints

Full type hints on function signatures and SQLAlchemy `Mapped[...]` columns, everywhere. This is what makes `Annotated[Session, Depends(get_db_session)]`-style FastAPI dependencies and editor tooling work without extra ceremony — treat a missing type hint on a new function as a gap to fill, not a style nit to skip.
