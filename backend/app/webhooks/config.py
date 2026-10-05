from functools import lru_cache
from uuid import UUID

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WebhookSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WEBHOOK_", extra="ignore")
    owner_id: UUID
    inbound_secret: SecretStr
    outbound_secret: SecretStr
    destination_url: str = "http://127.0.0.1:8091/catalog"
    max_attempts: int = Field(default=5, ge=1, le=20)
    lease_seconds: int = Field(default=30, ge=5, le=300)

    @field_validator("inbound_secret", "outbound_secret")
    @classmethod
    def strong_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("Use at least 32 characters")
        return value

    @field_validator("destination_url")
    @classmethod
    def configured_destination(cls, value: str) -> str:
        from urllib.parse import urlsplit

        url = urlsplit(value)
        if url.username or url.password or url.query or url.fragment:
            raise ValueError(
                "Destination must not contain credentials, query or fragment"
            )
        if url.scheme != "https" and not (
            url.scheme == "http"
            and url.hostname in {"127.0.0.1", "localhost", "receiver"}
        ):
            raise ValueError("HTTPS required except local demonstration receiver")
        return value

    @model_validator(mode="after")
    def separate_secrets(self) -> WebhookSettings:
        if self.inbound_secret == self.outbound_secret:
            raise ValueError("Inbound and outbound keys must differ")
        return self


@lru_cache
def config() -> WebhookSettings:
    return WebhookSettings()  # type: ignore[call-arg]
