import hashlib
import json
from typing import Callable

from django.db import transaction
from django.db.models import Count, OuterRef, Subquery
from django.utils import timezone

from .models import GENESIS_HASH, LedgerCheckpoint, LedgerSigningKey, Wallet, WalletTransaction


def _canonical_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _ledger_snapshot() -> tuple[str, int, int]:
    """Return a deterministic root hash, transaction count and wallet count."""
    latest_hash = WalletTransaction.objects.filter(
        wallet_id=OuterRef("pk")
    ).order_by("-sequence_number").values("entry_hash")[:1]
    latest_balance = WalletTransaction.objects.filter(
        wallet_id=OuterRef("pk")
    ).order_by("-sequence_number").values("balance_after_cents")[:1]
    latest_sequence = WalletTransaction.objects.filter(
        wallet_id=OuterRef("pk")
    ).order_by("-sequence_number").values("sequence_number")[:1]

    wallets = Wallet.objects.annotate(
        tx_count=Count("transactions"),
        latest_hash=Subquery(latest_hash),
        latest_balance=Subquery(latest_balance),
        latest_sequence=Subquery(latest_sequence),
    ).order_by("pk")

    leaves = []
    transaction_count = 0
    wallet_count = 0
    for wallet in wallets.iterator():
        wallet_count += 1
        transaction_count += wallet.tx_count
        if wallet.tx_count:
            if wallet.latest_balance != wallet.balance_cents:
                raise ValueError(
                    f"Wallet {wallet.pk} balance does not match its latest ledger entry."
                )
        elif wallet.balance_cents != 0:
            raise ValueError(
                f"Wallet {wallet.pk} has a non-zero balance but no ledger entries."
            )
        leaves.append({
            "wallet_id": str(wallet.pk),
            "balance_cents": wallet.balance_cents,
            "transaction_count": wallet.tx_count,
            "last_sequence": wallet.latest_sequence or 0,
            "last_entry_hash": wallet.latest_hash or GENESIS_HASH,
        })

    root_hash = hashlib.sha256(_canonical_bytes(leaves)).hexdigest()
    return root_hash, transaction_count, wallet_count


def _checkpoint_payload(checkpoint: LedgerCheckpoint) -> dict:
    return {
        "payload_version": checkpoint.payload_version,
        "checkpoint_number": checkpoint.checkpoint_number,
        "previous_checkpoint_hash": checkpoint.previous_checkpoint_hash,
        "ledger_root_hash": checkpoint.ledger_root_hash,
        "transaction_count": checkpoint.transaction_count,
        "wallet_count": checkpoint.wallet_count,
        "signing_key_id": checkpoint.signing_key.key_id,
        "created_at": checkpoint.created_at.isoformat(),
    }


@transaction.atomic
def create_ledger_checkpoint(*, signing_key_id, signer: Callable[[bytes], bytes]) -> LedgerCheckpoint:
    """Create a signed global checkpoint; signing keys remain external to PHM."""
    # Lock the key registry in a stable order so concurrent checkpoint creators
    # serialize even when they request different active keys.
    list(LedgerSigningKey.objects.select_for_update().order_by("pk").values_list("pk", flat=True))
    signing_key = LedgerSigningKey.objects.get(pk=signing_key_id)
    if signing_key.status != LedgerSigningKey.Status.ACTIVE:
        raise ValueError("The checkpoint signing key is not active.")

    previous = LedgerCheckpoint.objects.order_by("-checkpoint_number").first()
    root_hash, transaction_count, wallet_count = _ledger_snapshot()
    created_at = timezone.now()
    checkpoint = LedgerCheckpoint(
        checkpoint_number=(previous.checkpoint_number + 1) if previous else 1,
        previous_checkpoint_hash=previous.checkpoint_hash if previous else GENESIS_HASH,
        ledger_root_hash=root_hash,
        transaction_count=transaction_count,
        wallet_count=wallet_count,
        payload_version=1,
        signing_key=signing_key,
        created_at=created_at,
    )
    payload = _canonical_bytes(_checkpoint_payload(checkpoint))
    checkpoint.checkpoint_hash = hashlib.sha256(payload).hexdigest()
    signature = signer(payload)
    if not isinstance(signature, bytes) or not signature:
        raise ValueError("The signing provider returned an invalid checkpoint signature.")
    checkpoint.signature = signature
    checkpoint.save(force_insert=True)
    return checkpoint


def verify_ledger_checkpoint(
    checkpoint_id,
    *,
    verifier: Callable[[bytes, bytes, bytes], bool],
    compare_current_state: bool = False,
) -> bool:
    """Verify checkpoint hash/signature chain and optionally the latest live ledger root."""
    target = LedgerCheckpoint.objects.filter(pk=checkpoint_id).first()
    if target is None:
        return False

    expected_previous_hash = GENESIS_HASH
    checkpoints = LedgerCheckpoint.objects.filter(
        checkpoint_number__lte=target.checkpoint_number
    ).select_related("signing_key").order_by("checkpoint_number")

    last = None
    for expected_number, checkpoint in enumerate(checkpoints, start=1):
        if checkpoint.checkpoint_number != expected_number:
            return False
        if checkpoint.previous_checkpoint_hash != expected_previous_hash:
            return False
        payload = _canonical_bytes(_checkpoint_payload(checkpoint))
        if hashlib.sha256(payload).hexdigest() != checkpoint.checkpoint_hash:
            return False
        if not verifier(
            bytes(checkpoint.signing_key.public_key),
            payload,
            bytes(checkpoint.signature),
        ):
            return False
        expected_previous_hash = checkpoint.checkpoint_hash
        last = checkpoint

    if last is None or last.pk != target.pk:
        return False
    if compare_current_state:
        latest = LedgerCheckpoint.objects.order_by("-checkpoint_number").first()
        if latest is None or latest.pk != target.pk:
            return False
        root_hash, transaction_count, wallet_count = _ledger_snapshot()
        if (
            root_hash != target.ledger_root_hash
            or transaction_count != target.transaction_count
            or wallet_count != target.wallet_count
        ):
            return False
    return True
