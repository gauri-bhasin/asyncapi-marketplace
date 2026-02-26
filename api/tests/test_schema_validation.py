import json
from pathlib import Path

from jsonschema import validate


def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def test_weather_sample_matches_schema() -> None:
    base = Path(__file__).resolve().parents[2]
    doc = _load(str(base / "shared" / "asyncapi" / "weather_current_conditions.v1.json"))
    schema = doc["components"]["schemas"]["EventEnvelopeWeather"]
    sample = doc["components"]["messages"]["WeatherCurrentConditionsMessage"]["examples"][0]["payload"]
    validate(instance=sample, schema=schema)


def test_crypto_sample_matches_schema() -> None:
    base = Path(__file__).resolve().parents[2]
    doc = _load(str(base / "shared" / "asyncapi" / "crypto_price_updated.v1.json"))
    schema = doc["components"]["schemas"]["EventEnvelopeCrypto"]
    sample = doc["components"]["messages"]["CryptoPriceUpdatedMessage"]["examples"][0]["payload"]
    validate(instance=sample, schema=schema)
