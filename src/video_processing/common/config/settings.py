from sqlalchemy.engine import URL
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str | None = None
    database_host: str | None = None
    database_port: int | None = None
    database_username: str | None = None
    database_password: str | None = None
    database_name: str | None = None
    aws_region: str
    s3_bucket_name: str
    s3_endpoint_url: str | None = None
    s3_public_endpoint_url: str | None = None

    @property
    def sqlalchemy_database_url(self) -> str | URL:
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
        )


settings = Settings()
