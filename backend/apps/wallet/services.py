import hashlib
import json
from datetime import datetime
from typing import Callable

from django.db import transaction
from django.utils import timezone

from .models import GENESIS_HASH, LedgerSigningKey, Wallet, WalletHold, WalletTransaction


class WalletError(Exception):
    pass


class InsufficientFunds(WalletError):
    pass


class IdempotencyConflict(WalletError):
    pass


class InvalidLedgerOperation(WalletError):
    pass


class HoldNotActive(WalletError):
    pass


Signer = Callable[[bytes], bytes]


def _canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _validate_direction(transaction_type: str, amount_cents: int) -> None:
    if type(amount_cents) is not int or amount_cents == 0:
        raise InvalidLedgerOperation("A ledger transaction must be a non-zero integer number of cents.")
    if transaction_type in (WalletTransaction.Type.TOPUP, WalletTransaction.Type.REFUND):
        if amount_cents <= 0:
            raise InvalidLedgerOperation("Top-ups and refunds must be positive.")
    elif transaction_type == WalletTransaction.Type.PURCHASE:
        if amount_cents >= 0:
            raise InvalidLedgerOperation("Purchases must be negative.")
    elif transaction_type != WalletTransaction.Type.ADMIN_ADJUSTMENT:
        raise InvalidLedgerOperation("Unsupported transaction type.")


def _post_locked(
    wallet: Wallet,
    *,
    transaction_type: str,
    amount_cents: int,
    description: str,
    idempotency_key: str,
    signing_key: LedgerSigningKey,
    signer: Signer,
    reference: str = "",
    metadata: dict | None = None,
) -> WalletTransaction:
    _validate_direction(transaction_type, amount_cents)
    if not idempotency_key or len(idempotency_key) > 128:
        raise InvalidLedgerOperation("A valid idempotency key is required.")

    if not isinstance(metadata, dict):
        raise InvalidLedgerOperation("Transaction metadata must be an object.")
    metadata = metadata or {}
    existing = WalletTransaction.objects.filter(wallet=wallet, idempotency_key=idempotency_key).first()
    if existing:
        same_request = (
            existing.type == transaction_type
            and existing.amount_cents == amount_cents
            and existing.description == description
            and existing.reference == reference
            and existing.metadata == metadata
        )
        if not same_request:
            raise IdempotencyConflict("The idempotency key was already used for another operation.")
        return existing

    if signing_key.status != LedgerSigningKey.Status.ACTIVE:
        raise InvalidLedgerOperation("The signing key is not active.")

    new_balance = wallet.balance_cents + amount_cents
    if new_balance < 0:
        raise InsufficientFunds("The wallet balance is insufficient.")
    if amount_cents < 0 and wallet.available_balance_cents < abs(amount_cents):
        raise InsufficientFunds("The available balance is reserved or insufficient.")

    previous = wallet.transactions.order_by("-sequence_number").first()
    sequence_number = previous.sequence_number + 1 if previous else 1
    previous_hash = previous.entry_hash if previous else GENESIS_HASH
    created_at = timezone.now()

    payload = {
        "payload_version": 1,
        "wallet_id": str(wallet.pk),
        "sequence_number": sequence_number,
        "type": transaction_type,
        "amount_cents": amount_cents,
        "balance_after_cents": new_balance,
        "description": description,
        "idempotency_key": idempotency_key,
        "reference": reference,
        "metadata": metadata,
        "previous_hash": previous_hash,
        "signing_key_id": signing_key.key_id,
        "created_at": created_at.isoformat(),
    }
    canonical_payload = _canonical_bytes(payload)
    entry_hash = hashlib.sha256(canonical_payload).hexdigest()
    signature = signer(canonical_payload)
    if not isinstance(signature, bytes) or not signature:
        raise InvalidLedgerOperation("The signing provider returned an invalid signature.")

    entry = WalletTransaction.objects.create(
        wallet=wallet,
        sequence_number=sequence_number,
        type=transaction_type,
        amount_cents=amount_cents,
        balance_after_cents=new_balance,
        description=description,
        idempotency_key=idempotency_key,
        reference=reference,
        metadata=metadata,
        previous_hash=previous_hash,
        entry_hash=entry_hash,
        payload_version=1,
        signature=signature,
        signing_key=signing_key,
        created_at=created_at,
    )
    Wallet.objects.filter(pk=wallet.pk).update(balance_cents=new_balance, updated_at=created_at)
    wallet.balance_cents = new_balance
    wallet.updated_at = created_at
    return entry


@transaction.atomic
def post_transaction(
    wallet_id,
    *,
    transaction_type: str,
    amount_cents: int,
    description: str,
    idempotency_key: str,
    signing_key_id,
    signer: Signer,
    reference: str = "",
    metadata: dict | None = None,
) -> WalletTransaction:
    wallet = Wallet.objects.select_for_update().get(pk=wallet_id)
    signing_key = LedgerSigningKey.objects.get(pk=signing_key_id)
    return _post_locked(
        wallet,
        transaction_type=transaction_type,
        amount_cents=amount_cents,
        description=description,
        idempotency_key=idempotency_key,
        signing_key=signing_key,
        signer=signer,
        reference=reference,
        metadata=metadata,
    )


def credit_wallet(wallet_id, amount_cents: int, **kwargs) -> WalletTransaction:
    if type(amount_cents) is not int or amount_cents <= 0:
        raise InvalidLedgerOperation("Credit amount must be a positive integer number of cents.")
    return post_transaction(
        wallet_id,
        transaction_type=kwargs.pop("transaction_type", WalletTransaction.Type.TOPUP),
        amount_cents=amount_cents,
        **kwargs,
    )


def debit_wallet(wallet_id, amount_cents: int, **kwargs) -> WalletTransaction:
    if type(amount_cents) is not int or amount_cents <= 0:
        raise InvalidLedgerOperation("Debit amount must be a positive integer number of cents.")
    return post_transaction(
        wallet_id,
        transaction_type=WalletTransaction.Type.PURCHASE,
        amount_cents=-amount_cents,
        **kwargs,
    )


@transaction.atomic
def place_hold(
    wallet_id,
    *,
    amount_cents: int,
    idempotency_key: str,
    reference: str = "",
    expires_at: datetime | None = None,
    metadata: dict | None = None,
) -> WalletHold:
    if type(amount_cents) is not int or amount_cents <= 0:
        raise InvalidLedgerOperation("Hold amount must be a positive integer number of cents.")
    if not idempotency_key or len(idempotency_key) > 128:
        raise InvalidLedgerOperation("A valid hold idempotency key is required.")
    if metadata is not None and not isinstance(metadata, dict):
        raise InvalidLedgerOperation("Hold metadata must be an object.")
    if expires_at is not None and not timezone.is_aware(expires_at):
        raise InvalidLedgerOperation("Hold expiry must be timezone-aware.")
    wallet = Wallet.objects.select_for_update().get(pk=wallet_id)
    existing = WalletHold.objects.filter(wallet=wallet, idempotency_key=idempotency_key).first()
    if existing:
        if (
            existing.amount_cents != amount_cents
            or existing.reference != reference
            or existing.expires_at != expires_at
            or existing.metadata != (metadata or {})
        ):
            raise IdempotencyConflict("The hold idempotency key was already used.")
        return existing
    if wallet.available_balance_cents < amount_cents:
        raise InsufficientFunds("The available balance is insufficient for this hold.")
    return WalletHold.objects.create(
        wallet=wallet,
        amount_cents=amount_cents,
        idempotency_key=idempotency_key,
        reference=reference,
        expires_at=expires_at,
        metadata=metadata or {},
    )


@transaction.atomic
def capture_hold(hold_id, *, signing_key_id, signer: Signer) -> WalletTransaction | None:
    hold = WalletHold.objects.select_for_update().select_related("wallet").get(pk=hold_id)
    if hold.status == WalletHold.Status.CAPTURED:
        return hold.captured_transaction
    if hold.status != WalletHold.Status.ACTIVE:
        raise HoldNotActive("Only active holds can be captured.")
    now = timezone.now()
    if hold.expires_at and hold.expires_at <= now:
        hold.status = WalletHold.Status.EXPIRED
        hold.save(update_fields=["status", "updated_at"])
        return None

    wallet = Wallet.objects.select_for_update().get(pk=hold.wallet_id)
    signing_key = LedgerSigningKey.objects.get(pk=signing_key_id)
    entry = _post_locked(
        wallet,
        transaction_type=WalletTransaction.Type.PURCHASE,
        amount_cents=-hold.amount_cents,
        description=f"Capture hold {hold.pk}",
        idempotency_key=f"hold-capture:{hold.pk}",
        signing_key=signing_key,
        signer=signer,
        reference=hold.reference,
        metadata={**hold.metadata, "hold_id": str(hold.pk)},
    )
    hold.status = WalletHold.Status.CAPTURED
    hold.captured_transaction = entry
    hold.save(update_fields=["status", "captured_transaction", "updated_at"])
    return entry


@transaction.atomic
def release_hold(hold_id) -> WalletHold:
    hold = WalletHold.objects.select_for_update().get(pk=hold_id)
    if hold.status == WalletHold.Status.ACTIVE:
        hold.status = (
            WalletHold.Status.EXPIRED
            if hold.expires_at and hold.expires_at <= timezone.now()
            else WalletHold.Status.RELEASED
        )
        hold.save(update_fields=["status", "updated_at"])
    elif hold.status == WalletHold.Status.CAPTURED:
        raise HoldNotActive("A captured hold cannot be released.")
    return hold


def verify_wallet_chain(wallet_id, verifier: Callable[[bytes, bytes, bytes], bool]) -> bool:
    """Verify sequence, balance progression, hash links and signatures.

    The verifier receives (public_key, canonical_payload, signature); private keys
    remain outside the application database and are never loaded by this function.
    """
    wallet = Wallet.objects.get(pk=wallet_id)
    expected_balance = 0
    expected_previous_hash = GENESIS_HASH

    entries = wallet.transactions.select_related("signing_key").order_by("sequence_number")
    for expected_sequence, entry in enumerate(entries, start=1):
        if entry.sequence_number != expected_sequence:
            return False
        if entry.previous_hash != expected_previous_hash:
            return False

        payload = {
            "payload_version": entry.payload_version,
            "wallet_id": str(wallet.pk),
            "sequence_number": entry.sequence_number,
            "type": entry.type,
            "amount_cents": entry.amount_cents,
            "balance_after_cents": entry.balance_after_cents,
            "description": entry.description,
            "idempotency_key": entry.idempotency_key,
            "reference": entry.reference,
            "metadata": entry.metadata,
            "previous_hash": entry.previous_hash,
            "signing_key_id": entry.signing_key.key_id,
            "created_at": entry.created_at.isoformat(),
        }
        canonical_payload = _canonical_bytes(payload)
        if hashlib.sha256(canonical_payload).hexdigest() != entry.entry_hash:
            return False
        if not verifier(bytes(entry.signing_key.public_key), canonical_payload, bytes(entry.signature)):
            return False

        expected_balance += entry.amount_cents
        if expected_balance < 0 or entry.balance_after_cents != expected_balance:
            return False
        expected_previous_hash = entry.entry_hash

    return expected_balance == wallet.balance_cents
