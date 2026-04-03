import hmac
import hashlib

from ingest.app.security import verify_github_signature


def test_verify_github_signature_valid() -> None:
    secret = "top-secret"
    body = b'{"deployment":"ok"}'
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    header = f"sha256={digest}"
    assert verify_github_signature(secret, body, header)[0] is True


def test_verify_github_signature_invalid() -> None:
    assert verify_github_signature("secret", b"{}", "sha256=deadbeef")[0] is False
