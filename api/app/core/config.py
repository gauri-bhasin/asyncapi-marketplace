import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://marketplace:marketplace@localhost:5432/marketplace",
    )
    chroma_host: str = os.getenv("CHROMA_HOST", "localhost")
    chroma_port: int = int(os.getenv("CHROMA_PORT", "8001"))
    api_key_prefix: str = os.getenv("API_KEY_PREFIX", "mkp_")
    asyncapi_dir: Path = Path("/app/shared/asyncapi")

    # Rate limiting
    rate_limit_per_minute: int = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))

    # Solace (used by DLQ replay publisher)
    solace_host: str = os.getenv("SOLACE_HOST", "localhost")
    solace_port: int = int(os.getenv("SOLACE_PORT", "1883"))
    solace_username: str = os.getenv("SOLACE_USERNAME", "admin")
    solace_password: str = os.getenv("SOLACE_PASSWORD", "admin")

    # Event Portal (optional)
    event_portal_token: str = os.getenv("EVENT_PORTAL_TOKEN", "")

    @property
    def psycopg_dsn(self) -> str:
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")


settings = Settings()
