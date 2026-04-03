import hashlib
import hmac


def verify_github_signature(secret: str, body: bytes, signature_header: str | None) -> tuple[bool, str]:
    """Returns (ok, reason). reason is empty if ok else a short diagnostic."""
    secret = (secret or "").strip()
    if not secret:
        return True, ""
    if not signature_header:
        return False, "missing X-Hub-Signature-256 header"
    if not signature_header.strip().startswith("sha256="):
        return False, "X-Hub-Signature-256 must start with sha256="
    provided = signature_header.split("=", 1)[1].strip()
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, provided):
        return False, "signature mismatch (secret or body differs from GitHub)"
    return True, ""


def verify_sentry_token(configured_token: str, provided_token: str | None) -> bool:
    if not configured_token:
        return True
    if not provided_token:
        return False
    return hmac.compare_digest(configured_token, provided_token)
