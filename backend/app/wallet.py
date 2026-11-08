from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models import Wallet, WalletTransaction, WalletTransactionType


class WalletError(Exception):
    pass


class WalletNotFound(WalletError):
    pass


class InsufficientFunds(WalletError):
    pass


class InvalidWalletMutation(WalletError):
    pass


async def create_wallet(session: AsyncSession, customer_id: int) -> Wallet:
    if customer_id <= 0:
        raise InvalidWalletMutation("customer_id must be positive")
    wallet = Wallet(customer_id=customer_id, currency="EUR", balance_cents=0)
    session.add(wallet)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise InvalidWalletMutation("customer already has a wallet") from exc
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
    """Apply one ledger mutation. Positive amount credits; negative amount debits.

    Caller owns the surrounding database transaction. The row lock serializes
    concurrent changes to the same wallet on PostgreSQL.
    """
    if amount_cents == 0:
        raise InvalidWalletMutation("amount_cents must not be zero")
    if not idempotency_key or len(idempotency_key) > 128:
        raise InvalidWalletMutation("a valid idempotency key is required")
    if not description or len(description) > 255:
        raise InvalidWalletMutation("a description of 1-255 characters is required")

    wallet_result = await session.execute(
        select(Wallet).where(Wallet.customer_id == customer_id).with_for_update()
    )
    wallet = wallet_result.scalar_one_or_none()
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
        return existing

    if amount_cents < 0 and wallet.balance_cents + amount_cents < 0:
        raise InsufficientFunds("wallet balance is insufficient")

    if transaction_type == WalletTransactionType.TOPUP and amount_cents < 0:
        raise InvalidWalletMutation("topups must be credits")
    if transaction_type == WalletTransactionType.PURCHASE and amount_cents > 0:
        raise InvalidWalletMutation("purchases must be debits")

    wallet.balance_cents += amount_cents
    entry = WalletTransaction(
        wallet_id=wallet.id,
        transaction_type=transaction_type.value,
        amount_cents=abs(amount_cents),
        balance_after_cents=wallet.balance_cents,
        idempotency_key=idempotency_key,
        reference=reference,
        description=description,
    )
    # Keep sign separately in the transaction type: ledger amount is positive
    # magnitude, and type determines whether it is a credit or debit.
    if amount_cents < 0:
        entry.transaction_type = f"{transaction_type.value}_debit"
    session.add(entry)
    await session.flush()
    return entry
