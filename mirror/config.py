from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App
    app_env: str = "development"
    secret_key: SecretStr
    base_url: str

    # PostgreSQL
    database_url: SecretStr
    test_database_url: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr = SecretStr("")

    # RabbitMQ
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    # NATS
    nats_url: str = "nats://localhost:4222"

    # LLM
    openai_api_key: SecretStr
    anthropic_api_key: SecretStr

    # Telegram
    telegram_bot_token: SecretStr
    telegram_webhook_secret: SecretStr

    # Admin
    admin_token: SecretStr
    admin_username: str = "admin"
    admin_password: SecretStr = SecretStr("admin")

    # Polling mode for local dev (no public URL needed)
    polling_mode: bool = False

    # Sentry
    sentry_dsn: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Appsmith vars в .env нужны только docker-compose
    )


settings = Settings()
