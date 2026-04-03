import json
from pathlib import Path

from jsonschema import validate


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_github_sample_matches_schema() -> None:
    base = Path(__file__).resolve().parents[2]
    doc = _load(base / "shared" / "asyncapi" / "github_deployment.v1.json")
    schema = doc["components"]["schemas"]["EventEnvelope"]
    sample = doc["components"]["messages"]["GitHubDeploymentMessage"]["examples"][0]["payload"]
    validate(instance=sample, schema=schema)


def test_sentry_sample_matches_schema() -> None:
    base = Path(__file__).resolve().parents[2]
    doc = _load(base / "shared" / "asyncapi" / "sentry_error_event.v1.json")
    schema = doc["components"]["schemas"]["EventEnvelope"]
    sample = doc["components"]["messages"]["SentryErrorEventMessage"]["examples"][0]["payload"]
    validate(instance=sample, schema=schema)
