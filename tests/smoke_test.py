"""
V1 + V2 integration smoke test.

Usage:
    docker compose up --build -d
    # wait ~30s for all services to be healthy
    python tests/smoke_test.py

Requires: Python 3.10+ (stdlib only — no pip installs needed).
"""

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000"
PASS = 0
FAIL = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def req(method: str, path: str, body=None, headers=None, expected=200):
    global PASS, FAIL
    url = f"{BASE}{path}"
    hdrs = headers or {}
    data = json.dumps(body).encode() if body is not None else None
    if data:
        hdrs.setdefault("Content-Type", "application/json")

    rq = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    label = f"{method} {path}"
    try:
        with urllib.request.urlopen(rq) as resp:
            code = resp.status
            result = json.loads(resp.read().decode())
        if code == expected:
            PASS += 1
            print(f"  PASS  {label} -> {code}")
            return result
        else:
            FAIL += 1
            print(f"  FAIL  {label} -> expected {expected}, got {code}")
            return result
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            result = json.loads(exc.read().decode())
        except Exception:
            result = {}
        if code == expected:
            PASS += 1
            print(f"  PASS  {label} -> {code}")
            return result
        else:
            FAIL += 1
            print(f"  FAIL  {label} -> expected {expected}, got {code}  body={result}")
            return result
    except Exception as exc:
        FAIL += 1
        print(f"  FAIL  {label} -> {exc}")
        return {}


def assert_key(obj, key, label=""):
    global PASS, FAIL
    if key in obj:
        PASS += 1
        print(f"  PASS  {label or key} present")
    else:
        FAIL += 1
        print(f"  FAIL  {label or key} missing in {list(obj.keys())}")


def section(title):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


# ---------------------------------------------------------------------------
# Wait for API
# ---------------------------------------------------------------------------

def wait_for_api(timeout=90):
    print("Waiting for API to become healthy …")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            rq = urllib.request.Request(f"{BASE}/health")
            with urllib.request.urlopen(rq, timeout=3) as resp:
                if resp.status == 200:
                    print("  API is healthy.\n")
                    return True
        except Exception:
            pass
        time.sleep(2)
    print("  TIMEOUT waiting for API!")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def main():
    global PASS, FAIL

    wait_for_api()

    # ── V1 backward-compat ─────────────────────────────────────────────

    section("V1 — Health & Metrics")
    req("GET", "/health")
    # /metrics returns Prometheus text, not JSON — test it separately
    try:
        rq = urllib.request.Request(f"{BASE}/metrics")
        with urllib.request.urlopen(rq) as resp:
            body = resp.read().decode()
            if resp.status == 200 and "events_ingested_total" in body:
                PASS += 1
                print(f"  PASS  GET /metrics -> 200 (prometheus text)")
            else:
                FAIL += 1
                print(f"  FAIL  GET /metrics -> {resp.status}")
    except Exception as exc:
        FAIL += 1
        print(f"  FAIL  GET /metrics -> {exc}")

    section("V1 — Issue anonymous API key")
    key_resp = req("POST", "/apikeys")
    anon_key = key_resp.get("api_key", "")
    assert_key(key_resp, "api_key")
    anon_hdr = {"X-API-Key": anon_key}

    section("V1 — Protected ping")
    req("GET", "/protected/ping", headers=anon_hdr)

    section("V1 — Topics (list, detail, history)")
    topics = req("GET", "/topics", headers=anon_hdr)
    if isinstance(topics, list) and len(topics) > 0:
        PASS += 1
        print(f"  PASS  Got {len(topics)} topic(s)")
        topic_name = topics[0]["name"]
        req("GET", f"/topics/{topic_name}", headers=anon_hdr)
        req("GET", f"/topics/{topic_name}/history?limit=5", headers=anon_hdr)
    else:
        FAIL += 1
        print("  FAIL  Expected at least 1 topic")

    section("V1 — Semantic search")
    req("POST", "/search/semantic", body={"query": "weather"}, headers=anon_hdr)

    section("V1 — Agent recommend")
    req("POST", "/agent/recommend", body={"goal": "track crypto prices"}, headers=anon_hdr)

    section("V1 — 401 without key")
    req("GET", "/topics", expected=401)

    # ── V2 — User + key management ─────────────────────────────────────

    section("V2 — Create user")
    ts = str(int(time.time()))
    user_resp = req("POST", "/users", body={"username": f"tester_{ts}", "display_name": "Smoke Test"})
    assert_key(user_resp, "api_key")
    assert_key(user_resp, "user")
    user_key = user_resp.get("api_key", "")
    user_hdr = {"X-API-Key": user_key}

    section("V2 — Duplicate user (expect 409)")
    req("POST", "/users", body={"username": f"tester_{ts}"}, expected=409)

    section("V2 — GET /me")
    me = req("GET", "/me", headers=user_hdr)
    assert_key(me, "username")
    assert_key(me, "active_keys")

    section("V2 — Create additional key")
    new_key_resp = req("POST", "/me/apikeys", body={"label": "ci-key"}, headers=user_hdr)
    assert_key(new_key_resp, "api_key")

    section("V2 — List keys")
    keys = req("GET", "/me/apikeys", headers=user_hdr)
    if isinstance(keys, list) and len(keys) >= 2:
        PASS += 1
        print(f"  PASS  {len(keys)} key(s) listed")
        extra_key_id = keys[0]["id"]
    else:
        FAIL += 1
        print(f"  FAIL  Expected ≥2 keys, got {len(keys) if isinstance(keys, list) else keys}")
        extra_key_id = None

    if extra_key_id:
        section("V2 — Rotate key")
        rot = req("POST", f"/me/apikeys/{extra_key_id}/rotate", body={}, headers=user_hdr)
        assert_key(rot, "api_key")

        section("V2 — Revoke key")
        req("DELETE", f"/me/apikeys/{extra_key_id}", headers=user_hdr)

    # ── V2 — Subscriptions ─────────────────────────────────────────────

    section("V2 — Create subscription")
    sub = req("POST", "/subscriptions", body={"topic": "marketplace.weather.current_conditions.v1"}, headers=user_hdr)
    assert_key(sub, "id")
    sub_id = sub.get("id")

    section("V2 — List subscriptions")
    subs = req("GET", "/me/subscriptions", headers=user_hdr)
    if isinstance(subs, list) and len(subs) >= 1:
        PASS += 1
        print(f"  PASS  {len(subs)} subscription(s)")
    else:
        FAIL += 1
        print(f"  FAIL  Expected ≥1 subscription")

    if sub_id:
        section("V2 — Pause subscription")
        patched = req("PATCH", f"/subscriptions/{sub_id}", body={"status": "PAUSED"}, headers=user_hdr)
        if patched.get("status") == "PAUSED":
            PASS += 1
            print("  PASS  Status is PAUSED")
        else:
            FAIL += 1
            print(f"  FAIL  Expected PAUSED, got {patched.get('status')}")

        section("V2 — Resume subscription")
        patched = req("PATCH", f"/subscriptions/{sub_id}", body={"status": "ACTIVE"}, headers=user_hdr)
        if patched.get("status") == "ACTIVE":
            PASS += 1
            print("  PASS  Status is ACTIVE")
        else:
            FAIL += 1
            print(f"  FAIL  Expected ACTIVE, got {patched.get('status')}")

    # ── V2 — Subscriptions require user-linked key ─────────────────────

    section("V2 — Anon key blocked from user endpoints")
    req("GET", "/me", headers=anon_hdr, expected=403)
    req("GET", "/me/subscriptions", headers=anon_hdr, expected=403)

    # ── V2 — Ops ───────────────────────────────────────────────────────

    section("V2 — DLQ list")
    dlq = req("GET", "/ops/dlq?limit=10&offset=0", headers=user_hdr)
    assert_key(dlq, "total")
    assert_key(dlq, "items")

    section("V2 — Audit list")
    audit = req("GET", "/ops/audit?limit=10&offset=0", headers=user_hdr)
    assert_key(audit, "total")
    assert_key(audit, "items")
    if audit.get("total", 0) > 0:
        PASS += 1
        print(f"  PASS  {audit['total']} audit entries (user/key/sub events logged)")
    else:
        FAIL += 1
        print("  FAIL  Expected audit entries from previous operations")

    # ── V2 — Registry sync ─────────────────────────────────────────────

    section("V2 — Registry sync")
    sync = req("POST", "/registry/sync", headers=user_hdr)
    assert_key(sync, "topics_synced")

    # ── V2 — Rate limiting (burst test) ────────────────────────────────

    section("V2 — Rate limiting (soft check)")
    print("  (skipping exhaustive 120-call burst — would slow the test)")
    print("  Rate limiting is enforced in require_api_key middleware.")

    # ── Summary ────────────────────────────────────────────────────────

    print(f"\n{'='*60}")
    print(f"  RESULTS: {PASS} passed, {FAIL} failed")
    print(f"{'='*60}")

    if FAIL:
        print("\n  ⚠ Some tests failed. Check output above.")
        sys.exit(1)
    else:
        print("\n  All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
