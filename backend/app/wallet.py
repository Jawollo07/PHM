from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Wallet, WalletTransaction, WalletTransactionType


class WalletError(Exception):
    """Base class for expected wallet-domain errors."""


class WalletNotFound(WalletError):
    pass


class InsufficientFunds(WalletError):
    pass


class InvalidWalletMutation(WalletError):
    pass


class IdempotencyConflict(WalletError):
    pass


async def create_wallet(session: AsyncSession, customer_id: int) -> Wallet:
    if customer_id <= 0:
        raise InvalidWalletMutation("customer_id must be positive")
    wallet = Wallet(customer_id=customer_id, currency="EUR", balance_cents=0)
    session.add(wallet)
    await session.flush()
    return wallet


async def mutate_wallet(
    session: AsyncSession,
    *,
    customer_id: int,
    transaction_type: WalletTransactionType,
    amount_cents: int,
    idempotency_key: str,
    description: str,
    reference: str | None = None,
) -> WalletTransaction:
    """Apply one signed ledger entry inside the caller's DB transaction.

    PostgreSQL's row lock serializes all mutations for a wallet. The unique
    (wallet_id, idempotency_key) constraint is the final concurrency guard.
    Reusing a key with a different payload is rejected rather than silently
    returning an unrelated previous transaction.
    """
    if customer_id <= 0:
        raise InvalidWalletMutation("customer_id must be positive")
    if not isinstance(transaction_type, WalletTransactionType):
        raise InvalidWalletMutation("unsupported transaction type")
    if not isinstance(amount_cents, int) or isinstance(amount_cents, bool) or amount_cents == 0:
        raise InvalidWalletMutation("amount_cents must be a non-zero integer")
    if not idempotency_key or len(idempotency_key) > 128:
        raise InvalidWalletMutation("a valid idempotency key is required")
    if not description or len(description) > 255:
        raise InvalidWalletMutation("a description of 1-255 characters is required")
    if reference is not None and len(reference) > 128:
        raise InvalidWalletMutation("reference must be at most 128 characters")

    if transaction_type in (WalletTransactionType.TOPUP, WalletTransactionType.REFUND):
        if amount_cents < 0:
            raise InvalidWalletMutation(f"{transaction_type.value} must be a credit")
    elif transaction_type == WalletTransactionType.PURCHASE and amount_cents > 0:
        raise InvalidWalletMutation("purchase must be a debit")

    result = await session.execute(
        select(Wallet).where(Wallet.customer_id == customer_id).with_for_update()
    )
    wallet = result.scalar_one_or_none()
    if wallet is None:
        raise WalletNotFound("wallet does not exist")

    existing_result = await session.execute(
        select(WalletTransaction).where(
            WalletTransaction.wallet_id == wallet.id,
            WalletTransaction.idempotency_key == idempotency_key,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing is not None:
        same_request = (
            existing.transaction_type == transaction_type.value
            and existing.amount_cents == amount_cents
            and existing.description == description
            and existing.reference == reference
        )
        if not same_request:
            raise IdempotencyConflict("idempotency key was already used with another payload")
        return existing

    new_balance = wallet.balance_cents + amount_cents
    if new_balance < 0:
        raise InsufficientFunds("wallet balance is insufficient")

    wallet.balance_cents = new_balance
    entry = WalletTransaction(
        wallet_id=wallet.id,
        transaction_type=transaction_type.value,
        amount_cents=amount_cents,
        balance_after_cents=new_balance,
        idempotency_key=idempotency_key,
        reference=reference,
        description=description,
    )
    session.add(entry)
    await session.flush()
    return entry
