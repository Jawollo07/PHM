"""Create the initial single-wallet ledger.

Revision ID: 0001_wallet_ledger
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_wallet_ledger"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wallets",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="EUR", nullable=False),
        sa.Column("balance_cents", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("balance_cents >= 0", name="ck_wallet_nonnegative"),
        sa.CheckConstraint("currency = 'EUR'", name="ck_wallet_currency_eur"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id", name="uq_wallet_customer"),
    )
    op.create_index("ix_wallets_customer_id", "wallets", ["customer_id"], unique=False)

    op.create_table(
        "wallet_transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("wallet_id", sa.BigInteger(), nullable=False),
        sa.Column("transaction_type", sa.String(length=32), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("balance_after_cents", sa.BigInteger(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("reference", sa.String(length=128), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("amount_cents <> 0", name="ck_wallet_transaction_nonzero_amount"),
        sa.CheckConstraint(
            "balance_after_cents >= 0",
            name="ck_wallet_transaction_nonnegative_balance",
        ),
        sa.CheckConstraint(
            "transaction_type IN ('topup', 'purchase', 'refund', 'admin_adjustment')",
            name="ck_wallet_transaction_type",
        ),
        sa.CheckConstraint(
            "(transaction_type IN ('topup', 'refund') AND amount_cents > 0) OR "
            "(transaction_type = 'purchase' AND amount_cents < 0) OR "
            "transaction_type = 'admin_adjustment'",
            name="ck_wallet_transaction_direction",
        ),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wallet_id", "idempotency_key", name="uq_wallet_idempotency"),
    )
    op.create_index("ix_wallet_transactions_wallet_id", "wallet_transactions", ["wallet_id"])


def downgrade() -> None:
    op.drop_index("ix_wallet_transactions_wallet_id", table_name="wallet_transactions")
    op.drop_table("wallet_transactions")
    op.drop_index("ix_wallets_customer_id", table_name="wallets")
    op.drop_table("wallets")
