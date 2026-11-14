import base64
import hashlib
import stat
from pathlib import Path

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _private_key_from_hex(encoded_hex: str, source: str) -> Ed25519PrivateKey:
    if len(encoded_hex) != 128:
        raise ImproperlyConfigured(
            f"{source} must contain exactly 128 hexadecimal characters."
        )
    try:
        raw = bytes.fromhex(encoded_hex)
    except ValueError as exc:
        raise ImproperlyConfigured(
            f"{source} must contain exactly 128 hexadecimal characters."
        ) from exc
    if len(raw) != 64:
        raise ImproperlyConfigured(
            f"{source} must encode a 64-byte Ed25519 secret key."
        )
    # Expanded Ed25519 secrets encode the 32-byte seed followed by its public key.
    private_key = Ed25519PrivateKey.from_private_bytes(raw[:32])
    if private_key.public_key().public_bytes_raw() != raw[32:]:
        raise ImproperlyConfigured(
            f"The public-key portion of {source} does not match its private seed."
        )
    return private_key


def _private_key() -> Ed25519PrivateKey:
    key_file = getattr(settings, "WALLET_LEDGER_PRIVATE_KEY_FILE", "")
    encoded_hex = getattr(settings, "WALLET_LEDGER_PRIVATE_KEY_HEX", "")
    encoded = getattr(settings, "WALLET_LEDGER_PRIVATE_KEY_B64", "")
    if sum(bool(value) for value in (key_file, encoded_hex, encoded)) > 1:
        raise ImproperlyConfigured(
            "Configure only one of WALLET_LEDGER_PRIVATE_KEY_FILE, "
            "WALLET_LEDGER_PRIVATE_KEY_HEX, or WALLET_LEDGER_PRIVATE_KEY_B64."
        )
    if key_file:
        path = Path(key_file)
        try:
            file_info = path.stat()
            if not stat.S_ISREG(file_info.st_mode):
                raise ImproperlyConfigured(
                    "WALLET_LEDGER_PRIVATE_KEY_FILE must point to a regular file."
                )
            if stat.S_IMODE(file_info.st_mode) & 0o077:
                raise ImproperlyConfigured(
                    "WALLET_LEDGER_PRIVATE_KEY_FILE must not be accessible "
                    "by group or others; set its permissions to 0600."
                )
            pem_data = path.read_bytes()
        except OSError as exc:
            raise ImproperlyConfigured(
                "Could not read WALLET_LEDGER_PRIVATE_KEY_FILE."
            ) from exc
        if not pem_data.startswith(b"-----BEGIN"):
            try:
                encoded_hex = pem_data.decode("ascii").strip()
            except UnicodeDecodeError as exc:
                raise ImproperlyConfigured(
                    "WALLET_LEDGER_PRIVATE_KEY_FILE must contain an unencrypted "
                    "Ed25519 PEM key or a 128-character hexadecimal key."
                ) from exc
            return _private_key_from_hex(
                encoded_hex,
                "WALLET_LEDGER_PRIVATE_KEY_FILE",
            )
        try:
            private_key = load_pem_private_key(pem_data, password=None)
        except (TypeError, ValueError, UnsupportedAlgorithm) as exc:
            raise ImproperlyConfigured(
                "WALLET_LEDGER_PRIVATE_KEY_FILE must contain an unencrypted "
                "Ed25519 PEM private key."
            ) from exc
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ImproperlyConfigured(
                "WALLET_LEDGER_PRIVATE_KEY_FILE must contain an Ed25519 private key."
            )
        return private_key
    if encoded_hex:
        return _private_key_from_hex(
            encoded_hex,
            "WALLET_LEDGER_PRIVATE_KEY_HEX",
        )
    if not encoded:
        raise ImproperlyConfigured(
            "No wallet private key source is configured. Set "
            "WALLET_LEDGER_PRIVATE_KEY_FILE."
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
    """Sign ledger payloads with the configured external Ed25519 private key."""
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


def public_key_from_configured_key() -> tuple[bytes, str]:
    public_key = _private_key().public_key().public_bytes_raw()
    return public_key, hashlib.sha256(public_key).hexdigest()
