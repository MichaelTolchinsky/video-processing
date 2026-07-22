from pydantic_settings import BaseSettings
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    database_url: str | None = None
    database_host: str | None = None
    database_port: int | None = None
    database_username: str | None = None
    database_password: str | None = None
    database_name: str | None = None
    # Differ per process: the API needs real concurrency (many simultaneous
    # HTTP requests); the worker's poll loop is strictly serial (one job at a
    # time) and never needs more than one connection. Set per-container in
    # services_stack.py / docker-compose.yaml rather than sharing one value.
    db_pool_size: int = 5
    db_max_overflow: int = 5
    # How long to wait for a pooled connection before giving up. Short on the
    # API so an exhausted pool fails fast (503) instead of every request
    # queuing for the full default (30s), which is what turns a capacity
    # limit into a cascading pileup.
    db_pool_timeout: int = 30
    aws_region: str
    s3_bucket_name: str
    s3_endpoint_url: str | None = None
    s3_public_endpoint_url: str | None = None
    sqs_queue_url: str | None = None
    sqs_endpoint_url: str | None = None

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url is not None:
            return self.database_url

        if (
            self.database_host is None
            or self.database_port is None
            or self.database_username is None
            or self.database_password is None
            or self.database_name is None
        ):
            raise ValueError(
                "Set DATABASE_URL or all ECS database connection settings"
            )

        return URL.create(
            "postgresql+psycopg",
            username=self.database_username,
            password=self.database_password,
            host=self.database_host,
            port=self.database_port,
            database=self.database_name,
        ).render_as_string(hide_password=False)

    @property
    def async_sqlalchemy_database_url(self) -> str:
        """Same connection, asyncpg driver -- used by the API/worker engine.

        Alembic (sqlalchemy_database_url, psycopg) stays sync: migrations
        don't run concurrently, so there's nothing for async to buy there.
        """
        return self.sqlalchemy_database_url.replace(
            "postgresql+psycopg://", "postgresql+asyncpg://", 1
        )


settings = Settings()
