import os

from common import ensure_dlq_table, setup_logging
from crypto_connector import run as run_crypto
from weather_connector import run as run_weather


def main() -> None:
    setup_logging()
    ensure_dlq_table()
    connector_kind = os.getenv("CONNECTOR_KIND", "weather").lower()

    if connector_kind == "runner":
        from runner import main as run_all
        run_all()
    elif connector_kind == "weather":
        run_weather()
    elif connector_kind == "crypto":
        run_crypto()
    else:
        raise ValueError(f"Unsupported connector kind: {connector_kind}")


if __name__ == "__main__":
    main()
