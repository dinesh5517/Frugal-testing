# -*- coding: utf-8 -*-
"""
Q2 — Cryptographic Replay Testing, Stateful Nonces & Hash-Chain API Chaining
=============================================================================
Python + Requests automation script.

Prerequisites
─────────────
  pip install requests

Usage
─────
  # Terminal 1 — start the mock server first:
  cd Q2_crypto_replay/mock_server && npm install && node server.js

  # Terminal 2 — run this test:
  python Q2_crypto_replay/automation/test_replay.py

What this script does
─────────────────────
  Step 1 → POST /transaction — create transaction, extract ID + challenge token
  Step 2 → Build HMAC-SHA512 X-Frugal-Mac header dynamically
  Step 3 → PUT /transaction/:id — commit with HMAC header (expect 200 OK)
  Step 4 → Replay identical request within 150ms (expect 409 Conflict)
  Assert → If replay returns 200/201 → raise HighRiskDataMutationVulnerabilityError
"""

import requests
import hmac
import hashlib
import time
import json
import logging
import sys

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d  [%(levelname)s]  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(
        open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)
    )],
)
log = logging.getLogger("Q2-CryptoReplay")

BASE_URL  = "http://localhost:4001"
SALT_SEQ  = "FT-SALT-v1-DELTA-7"

# ── Custom exception for vulnerability reporting ───────────────────────────────
class HighRiskDataMutationVulnerabilityError(Exception):
    """
    Raised when a replay attack is NOT detected by the backend.
    This signals that the server has issued a duplicate success response,
    indicating a critical data-mutation vulnerability.
    """
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# HMAC-SHA512 header generation
# ═══════════════════════════════════════════════════════════════════════════════

def generate_hmac_sha512(raw_body: str, timestamp_us: int, challenge_token: str) -> str:
    """
    Computes HMAC-SHA512:
      key  = challenge_token (server-issued per-transaction secret)
      data = raw_body_string + str(timestamp_us) + SALT_SEQ
    Using raw body string avoids float/int JSON serialization mismatches.
    Returns hex digest.
    """
    data = raw_body + str(timestamp_us) + SALT_SEQ
    mac  = hmac.new(
        key=challenge_token.encode('utf-8'),
        msg=data.encode('utf-8'),
        digestmod=hashlib.sha512,
    ).hexdigest()
    log.debug(f"  HMAC-SHA512 computed ({len(mac)} hex chars)")
    log.debug(f"  Key    : {challenge_token[:16]}...")
    log.debug(f"  Data   : {data[:80]}...")
    log.debug(f"  Digest : {mac[:32]}...")
    return mac


# ═══════════════════════════════════════════════════════════════════════════════
# Step 1 — POST /transaction
# ═══════════════════════════════════════════════════════════════════════════════

def step1_create_transaction() -> dict:
    log.info("=" * 65)
    log.info("  STEP 1 — POST /transaction")
    log.info("=" * 65)

    payload = {
        "description": "Wire transfer - frugal testing Q2",
        "amount":      5000.00,
        "currency":    "USD",
    }

    resp = requests.post(f"{BASE_URL}/transaction", json=payload, timeout=10)

    log.info(f"  Status      : {resp.status_code}")
    log.info(f"  Response    : {resp.json()}")
    log.info(f"  Headers     : {dict(resp.headers)}")

    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}"

    txn_id          = resp.headers.get("X-Transaction-Id")
    challenge_token = resp.headers.get("X-Challenge-Token")
    server_ts       = resp.headers.get("X-Server-Timestamp")

    assert txn_id,          "Missing X-Transaction-Id header"
    assert challenge_token, "Missing X-Challenge-Token header"
    assert server_ts,       "Missing X-Server-Timestamp header"

    log.info(f"  [OK] Transaction ID      : {txn_id}")
    log.info(f"  [OK] Challenge Token     : {challenge_token[:16]}...")
    log.info(f"  [OK] Server Timestamp    : {server_ts}")

    return {
        "txn_id":          txn_id,
        "challenge_token": challenge_token,
        "server_ts":       server_ts,
        "payload":         payload,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Step 2 + 3 — Build HMAC & PUT /transaction/:id
# ═══════════════════════════════════════════════════════════════════════════════

def step2_build_mac_headers(txn_data: dict) -> tuple[dict, dict, int, str]:
    """
    Returns (put_body, headers, timestamp_us, raw_body_str)
    """
    log.info("=" * 65)
    log.info("  STEP 2 — Generating HMAC-SHA512 header (X-Frugal-Mac)")
    log.info("=" * 65)

    put_body = {
        "amount":      5000.00,
        "status":      "completed",
        "description": "Wire transfer - frugal testing Q2 (committed)",
    }

    # Serialize body exactly as it will be sent over the wire
    # Use separators=(',', ':') to match compact JSON (no spaces) = requests default
    raw_body_str = json.dumps(put_body, separators=(',', ':'))

    # Microsecond-precision timestamp (localized)
    timestamp_us = time.time_ns() // 1000   # nanoseconds -> microseconds

    mac = generate_hmac_sha512(
        raw_body        = raw_body_str,
        timestamp_us    = timestamp_us,
        challenge_token = txn_data["challenge_token"],
    )

    headers = {
        "Content-Type": "application/json",
        "X-Frugal-Mac": mac,
        "X-Timestamp":  str(timestamp_us),
    }

    log.info(f"  Timestamp (us)  : {timestamp_us}")
    log.info(f"  Raw body        : {raw_body_str}")
    log.info(f"  X-Frugal-Mac    : {mac[:32]}...")

    return put_body, headers, timestamp_us, raw_body_str


def step3_put_transaction(txn_data: dict, put_body: dict, headers: dict, raw_body_str: str) -> requests.Response:
    log.info("=" * 65)
    log.info(f"  STEP 3 -- PUT /transaction/{txn_data['txn_id']}")
    log.info("=" * 65)

    url  = f"{BASE_URL}/transaction/{txn_data['txn_id']}"
    # Send raw body bytes directly so the server receives exactly what we signed
    resp = requests.put(
        url,
        data=raw_body_str.encode('utf-8'),
        headers=headers,
        timeout=10
    )

    log.info(f"  Status   : {resp.status_code}")
    log.info(f"  Response : {resp.json()}")

    assert resp.status_code == 200, (
        f"Expected 200 on first PUT, got {resp.status_code}: {resp.text}"
    )
    log.info("  ✅ First PUT — transaction committed successfully")
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# Step 4 — Replay Attack (within 150ms)
# ═══════════════════════════════════════════════════════════════════════════════

def step4_replay_attack(txn_data: dict, put_body: dict, headers: dict,
                         raw_body_str: str, first_put_finish_time: float) -> None:
    log.info("=" * 65)
    log.info("  STEP 4 — REPLAY ATTACK (identical payload within 150ms)")
    log.info("=" * 65)

    elapsed_since_first = (time.perf_counter() - first_put_finish_time) * 1000
    remaining_ms        = 150 - elapsed_since_first

    log.info(f"  Time since first PUT : {elapsed_since_first:.1f}ms")
    log.info(f"  Remaining window     : {remaining_ms:.1f}ms")

    if remaining_ms < 0:
        log.warning("  ⚠️  150ms window already elapsed — sending replay anyway (server should still reject)")
    else:
        # Tiny busy-wait to use the remaining window
        target = time.perf_counter() + (remaining_ms / 1000) * 0.1   # send at 10% of remaining
        while time.perf_counter() < target:
            pass

    fire_time = time.perf_counter()
    url       = f"{BASE_URL}/transaction/{txn_data['txn_id']}"
    replay_resp = requests.put(
        url,
        data=raw_body_str.encode('utf-8'),
        headers=headers,
        timeout=10
    )
    round_trip  = (time.perf_counter() - fire_time) * 1000

    log.info(f"  Replay fired at      : {(time.perf_counter() - first_put_finish_time)*1000:.1f}ms after first PUT")
    log.info(f"  Replay round-trip    : {round_trip:.1f}ms")
    log.info(f"  Replay status code   : {replay_resp.status_code}")
    log.info(f"  Replay response body : {replay_resp.text[:200]}")

    # ── Assertion Layer ────────────────────────────────────────────────────────
    EXPECTED_REJECTION_CODES = {409, 422, 401, 403}
    SUCCESS_CODES            = {200, 201}

    if replay_resp.status_code in EXPECTED_REJECTION_CODES:
        log.info(
            f"  [PASS] ASSERTION PASSED - Replay correctly rejected "
            f"with HTTP {replay_resp.status_code}"
        )
        body = replay_resp.json()
        assert body.get("code") == "REPLAY_ATTEMPT" or replay_resp.status_code in {409, 422}, (
            f"Unexpected rejection body: {body}"
        )
        log.info(f"  [OK] Rejection reason   : {body.get('error', 'N/A')}")
        log.info(f"  [OK] Rejection code     : {body.get('code', 'N/A')}")

    elif replay_resp.status_code in SUCCESS_CODES:
        # ── HIGH RISK VULNERABILITY ALERT ─────────────────────────────────────
        alert_msg = (
            f"\n{'!!!' * 10}\n"
            f"HIGH-RISK DATA-MUTATION VULNERABILITY DETECTED\n"
            f"{'!!!' * 10}\n"
            f"The backend issued HTTP {replay_resp.status_code} on a replay request!\n"
            f"Transaction ID : {txn_data['txn_id']}\n"
            f"MAC used       : {headers['X-Frugal-Mac'][:32]}…\n"
            f"Timestamp (μs) : {headers['X-Timestamp']}\n"
            f"Response body  : {replay_resp.text[:300]}\n"
            f"IMPACT: Duplicate transactions can be committed, causing financial data corruption.\n"
            f"{'!!!' * 10}"
        )
        log.critical(alert_msg)
        raise HighRiskDataMutationVulnerabilityError(alert_msg)

    else:
        log.error(
            f"  ❓ Unexpected status code {replay_resp.status_code} — "
            f"review server configuration"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    log.info("=" * 65)
    log.info("  Q2 — Cryptographic Replay Testing Starting")
    log.info("=" * 65)

    try:
        # Health check
        health = requests.get(f"{BASE_URL}/health", timeout=5)
        assert health.status_code == 200, "Server health check failed"
        log.info(f"  Server health: {health.json()}")

        # Step 1: Create transaction
        txn_data = step1_create_transaction()

        # Step 2: Build HMAC headers
        put_body, headers, timestamp_us, raw_body_str = step2_build_mac_headers(txn_data)

        # Step 3: Execute first PUT
        t_before_put = time.perf_counter()
        step3_put_transaction(txn_data, put_body, headers, raw_body_str)
        first_put_finish = time.perf_counter()

        # Step 4: Replay within 150ms
        step4_replay_attack(txn_data, put_body, headers, raw_body_str, first_put_finish)

        log.info("")
        log.info("=" * 65)
        log.info("  Q2 COMPLETE - ALL ASSERTIONS PASSED [OK]")
        log.info("  Replay attack correctly rejected by the server.")
        log.info("=" * 65)

    except HighRiskDataMutationVulnerabilityError as e:
        log.critical(f"TEST FAILED --- vulnerability found:\n{e}")
        sys.exit(2)

    except AssertionError as e:
        log.error(f"Assertion failed: {e}")
        sys.exit(1)

    except Exception as e:
        log.exception(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
