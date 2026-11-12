import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _private_key() -> Ed25519PrivateKey:
    encoded = getattr(settings, "WALLET_LEDGER_PRIVATE_KEY_B64", "")
    if not encoded:
        raise ImproperlyConfigured(
            "WALLET_LEDGER_PRIVATE_KEY_B64 is not configured."
        )
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ImproperlyConfigured(
            "WALLET_LEDGER_PRIVATE_KEY_B64 must be valid Base64."
        ) from exc
    if len(raw) != 32:
        raise ImproperlyConfigured(
            "The Ed25519 private key seed must contain exactly 32 bytes."
        )
    return Ed25519PrivateKey.from_private_bytes(raw)


def sign_payload(payload: bytes) -> bytes:
    """Sign ledger payloads with a private key supplied only through the secret environment."""
    if not isinstance(payload, bytes):
        raise TypeError("Ledger payload must be bytes.")
    return _private_key().sign(payload)


def verify_payload(public_key: bytes, payload: bytes, signature: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes(public_key)).verify(
            bytes(signature),
            bytes(payload),
        )
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def public_key_from_environment() -> tuple[bytes, str]:
    public_key = _private_key().public_key().public_bytes_raw()
    return public_key, hashlib.sha256(public_key).hexdigest()
