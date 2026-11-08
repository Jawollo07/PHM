from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WalletTransactionType(StrEnum):
    TOPUP = "topup"
    PURCHASE = "purchase"
    REFUND = "refund"
    ADMIN_ADJUSTMENT = "admin_adjustment"


def _pk_type():
    # SQLite needs INTEGER for implicit autoincrement in the test suite.
    return BigInteger().with_variant(Integer, "sqlite")


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint("customer_id", name="uq_wallet_customer"),
        CheckConstraint("balance_cents >= 0", name="ck_wallet_nonnegative"),
        CheckConstraint("currency = 'EUR'", name="ck_wallet_currency_eur"),
    )

    id: Mapped[int] = mapped_column(_pk_type(), primary_key=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    balance_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    __table_args__ = (
        UniqueConstraint("wallet_id", "idempotency_key", name="uq_wallet_idempotency"),
        CheckConstraint("amount_cents <> 0", name="ck_wallet_transaction_nonzero_amount"),
        CheckConstraint("balance_after_cents >= 0", name="ck_wallet_transaction_nonnegative_balance"),
        CheckConstraint(
            "transaction_type IN ('topup', 'purchase', 'refund', 'admin_adjustment')",
            name="ck_wallet_transaction_type",
        ),
        CheckConstraint(
            "(transaction_type IN ('topup', 'refund') AND amount_cents > 0) OR "
            "(transaction_type = 'purchase' AND amount_cents < 0) OR "
            "transaction_type = 'admin_adjustment'",
            name="ck_wallet_transaction_direction",
        ),
    )

    id: Mapped[int] = mapped_column(_pk_type(), primary_key=True)
    wallet_id: Mapped[int] = mapped_column(
        ForeignKey("wallets.id", ondelete="RESTRICT"), index=True, nullable=False
    )
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # Signed EUR cents: credits are positive, debits are negative.
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    balance_after_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
