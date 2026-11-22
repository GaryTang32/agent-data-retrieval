"""Allow tokens (Phase 4 spec §12.6, P23): an HMAC-SHA-256, hex, over the canonical JSON (sorted
keys, no padding, UTF-8) of `{"decision", "instance", "request", "seq"}` (`instance`: the gate
process's random instance id, so a restarted gate's sequence numbers never collide) with a key
shared by the gate and the environment and never by the agent loop. The gate signs allows only;
the environment executes a side effect only with a token that verifies, once (single use is the
client's record of seen sequence numbers, `client.GateClient.check_token`). A key is at least
`MIN_KEY_BYTES` bytes; it is never logged, written or put in an exception message."""

from __future__ import annotations

import hashlib
import hmac
import json

__all__ = ["MIN_KEY_BYTES", "sign", "verify"]

MIN_KEY_BYTES = 32


def _payload(request: dict, decision: str, seq: int, instance: str) -> bytes:
    return json.dumps({"decision": decision, "instance": instance, "request": request,
                       "seq": seq}, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _check_key(key: object) -> bytes:
    if not isinstance(key, bytes) or len(key) < MIN_KEY_BYTES:
        raise ValueError(f"a token key is at least {MIN_KEY_BYTES} bytes")
    return key


def sign(key: bytes, request: dict, decision: str, seq: int, instance: str) -> str:
    """The token of `decision` on `request` at sequence number `seq` of gate `instance`.
    ValueError for a short key or a request that is not JSON."""
    return hmac.new(_check_key(key), _payload(request, decision, seq, instance),
                    hashlib.sha256).hexdigest()


def verify(key: bytes, token: object, request: dict, decision: str, seq: object,
           instance: object) -> bool:
    """Whether `token` is the token of (`request`, `decision`, `seq`, `instance`) under `key`;
    False for any malformed input (never raises)."""
    if not isinstance(token, str) or type(seq) is not int or not isinstance(instance, str):
        return False
    try:
        return hmac.compare_digest(sign(key, request, decision, seq, instance), token)
    except (ValueError, TypeError):
        return False
