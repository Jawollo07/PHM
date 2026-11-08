import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from backend.app.models import Base, Wallet, WalletTransaction, WalletTransactionType
from backend.app.wallet import (
    IdempotencyConflict,
    InsufficientFunds,
    InvalidWalletMutation,
    WalletNotFound,
    create_wallet,
    mutate_wallet,
)


async def make_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_wallet_is_unique_per_customer():
    async def scenario():
        engine, sessions = await make_session()
        try:
            async with sessions() as session:
                async with session.begin():
                    await create_wallet(session, 42)
            async with sessions() as session:
                async with session.begin():
                    with pytest.raises(IntegrityError):
                        await create_wallet(session, 42)
        finally:
            await engine.dispose()
    asyncio.run(scenario())


def test_topup_and_purchase_use_signed_cents_and_one_balance():
    async def scenario():
        engine, sessions = await make_session()
        try:
            async with sessions() as session:
                async with session.begin():
                    await create_wallet(session, 1)
            async with sessions() as session:
                async with session.begin():
                    credit = await mutate_wallet(
                        session, customer_id=1, transaction_type=WalletTransactionType.TOPUP,
                        amount_cents=2500, idempotency_key="provider:abc",
                        description="Manual test top-up",
                    )
                    debit = await mutate_wallet(
                        session, customer_id=1, transaction_type=WalletTransactionType.PURCHASE,
                        amount_cents=-799, idempotency_key="order:123",
                        description="Game server order",
                    )
                    assert credit.amount_cents == 2500
                    assert debit.amount_cents == -799
                    assert debit.balance_after_cents == 1701
            async with sessions() as session:
                wallet = await session.scalar(select(Wallet).where(Wallet.customer_id == 1))
                assert wallet.balance_cents == 1701
                entries = list((await session.scalars(select(WalletTransaction))).all())
                assert len(entries) == 2
        finally:
            await engine.dispose()
    asyncio.run(scenario())


def test_insufficient_funds_do_not_change_balance():
    async def scenario():
        engine, sessions = await make_session()
        try:
            async with sessions() as session:
                async with session.begin():
                    await create_wallet(session, 2)
            async with sessions() as session:
                with pytest.raises(InsufficientFunds):
                    async with session.begin():
                        await mutate_wallet(
                            session, customer_id=2, transaction_type=WalletTransactionType.PURCHASE,
                            amount_cents=-1, idempotency_key="order:no-funds",
                            description="Must fail",
                        )
            async with sessions() as session:
                wallet = await session.scalar(select(Wallet).where(Wallet.customer_id == 2))
                assert wallet.balance_cents == 0
        finally:
            await engine.dispose()
    asyncio.run(scenario())


def test_same_idempotent_request_returns_existing_entry():
    async def scenario():
        engine, sessions = await make_session()
        try:
            async with sessions() as session:
                async with session.begin():
                    await create_wallet(session, 3)
            async with sessions() as session:
                async with session.begin():
                    first = await mutate_wallet(
                        session, customer_id=3, transaction_type=WalletTransactionType.TOPUP,
                        amount_cents=1000, idempotency_key="same-key", description="Top-up",
                    )
                    second = await mutate_wallet(
                        session, customer_id=3, transaction_type=WalletTransactionType.TOPUP,
                        amount_cents=1000, idempotency_key="same-key", description="Top-up",
                    )
                    assert first.id == second.id
            async with sessions() as session:
                wallet = await session.scalar(select(Wallet).where(Wallet.customer_id == 3))
                assert wallet.balance_cents == 1000
        finally:
            await engine.dispose()
    asyncio.run(scenario())


def test_idempotency_key_with_different_payload_is_rejected():
    async def scenario():
        engine, sessions = await make_session()
        try:
            async with sessions() as session:
                async with session.begin():
                    await create_wallet(session, 4)
            async with sessions() as session:
                with pytest.raises(IdempotencyConflict):
                    async with session.begin():
                        await mutate_wallet(
                            session, customer_id=4, transaction_type=WalletTransactionType.TOPUP,
                            amount_cents=1000, idempotency_key="reused", description="Original",
                        )
                        await mutate_wallet(
                            session, customer_id=4, transaction_type=WalletTransactionType.TOPUP,
                            amount_cents=2000, idempotency_key="reused", description="Changed",
                        )
        finally:
            await engine.dispose()
    asyncio.run(scenario())


def test_invalid_direction_and_missing_wallet_are_rejected():
    async def scenario():
        engine, sessions = await make_session()
        try:
            async with sessions() as session:
                with pytest.raises(WalletNotFound):
                    async with session.begin():
                        await mutate_wallet(
                            session, customer_id=999, transaction_type=WalletTransactionType.TOPUP,
                            amount_cents=100, idempotency_key="missing", description="No wallet",
                        )
            async with sessions() as session:
                async with session.begin():
                    await create_wallet(session, 5)
            async with sessions() as session:
                with pytest.raises(InvalidWalletMutation):
                    async with session.begin():
                        await mutate_wallet(
                            session, customer_id=5, transaction_type=WalletTransactionType.TOPUP,
                            amount_cents=-100, idempotency_key="bad-direction",
                            description="Invalid top-up",
                        )
        finally:
            await engine.dispose()
    asyncio.run(scenario())
