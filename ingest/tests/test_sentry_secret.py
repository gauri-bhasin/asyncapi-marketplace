from ingest.app.security import verify_sentry_token


def test_verify_sentry_token_allows_when_not_configured() -> None:
    assert verify_sentry_token("", None) is True


def test_verify_sentry_token_accepts_match() -> None:
    assert verify_sentry_token("sentry-secret", "sentry-secret") is True


def test_verify_sentry_token_rejects_mismatch() -> None:
    assert verify_sentry_token("sentry-secret", "bad-token") is False
