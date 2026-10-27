from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AURAMCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    deployment_profile: str = "development"
    host: str = "127.0.0.1"
    port: int = 8020
    log_level: str = "INFO"
    hands_workload_token: str = Field(default="", repr=False)
    hands_workload_token_file: str | None = None
    admin_token: str = Field(default="", repr=False)
    admin_token_file: str | None = None
    allow_insecure_identity: bool = True
    platform_store: str = "postgres"
    db_type: str = "postgresql"
    db_host: str = ""
    db_port: int = 5432
    db_user: str = ""
    db_password: str = Field(default="", repr=False)
    db_password_file: str | None = None
    db_name: str = ""
    db_sslmode: str = "prefer"
    page_size: int = Field(default=50, ge=1, le=200)
    max_response_bytes: int = Field(default=1 * 1024 * 1024, ge=1024)
    analytics_config_file: str | None = None

    @model_validator(mode="after")
    def validate_production(self) -> Settings:
        for name in ("hands_workload_token", "admin_token", "db_password"):
            filename = getattr(self, f"{name}_file")
            if filename and not getattr(self, name):
                setattr(self, name, Path(filename).read_text().strip())
        if self.deployment_profile == "production" and self.allow_insecure_identity:
            raise ValueError("AURAMCP_ALLOW_INSECURE_IDENTITY cannot be true in production")
        if self.deployment_profile == "production" and not self.hands_workload_token:
            raise ValueError("production requires AURAMCP_HANDS_WORKLOAD_TOKEN")
        if self.deployment_profile == "production" and not self.admin_token:
            raise ValueError("production requires AURAMCP_ADMIN_TOKEN")
        if self.platform_store not in {"postgres", "memory"}:
            raise ValueError("AURAMCP_PLATFORM_STORE must be postgres or memory")
        if self.db_type != "postgresql":
            raise ValueError("AURAMCP_DB_TYPE must be postgresql")
        return self

    @property
    def resolved_db_name(self) -> str:
        return self.db_name or "auramcp"

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{quote(self.db_user, safe='')}:{quote(self.db_password, safe='')}"
            f"@{self.db_host}:{self.db_port}/{self.resolved_db_name}"
            f"?sslmode={self.db_sslmode}"
        )
