import os
from dataclasses import dataclass
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

    @property
    def psycopg_dsn(self) -> str:
        return self.database_url.replace("postgresql+psycopg://", "postgresql://")


settings = Settings()
