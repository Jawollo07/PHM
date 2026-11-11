from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.wallet.models import LedgerSigningKey, Wallet, WalletHold, WalletTransaction


class WalletModelTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="wallet-user",
            email="wallet@example.com",
            password="secure-test-password",
        )
        self.wallet = self.user.customer.wallet

    def test_user_creation_creates_exactly_one_wallet(self):
        self.assertEqual(Wallet.objects.filter(customer=self.user.customer).count(), 1)

    def test_wallet_available_balance_excludes_active_holds(self):
        self.wallet.balance_cents = 2500
        self.wallet.save(update_fields=["balance_cents", "updated_at"])
        WalletHold.objects.create(
            wallet=self.wallet,
            amount_cents=700,
            idempotency_key="hold-001",
        )

        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.reserved_balance_cents, 700)
        self.assertEqual(self.wallet.available_balance_cents, 1800)

    def test_wallet_balance_cannot_be_negative(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.filter(pk=self.wallet.pk).update(balance_cents=-1)

    def test_transaction_cannot_be_updated_or_deleted(self):
        key = LedgerSigningKey.objects.create(
            key_id="test-key",
            label="Test key",
            public_key=b"public-key",
            fingerprint="a" * 64,
        )
        entry = WalletTransaction.objects.create(
            wallet=self.wallet,
            sequence_number=1,
            type=WalletTransaction.Type.TOPUP,
            amount_cents=500,
            balance_after_cents=500,
            description="Test credit",
            idempotency_key="credit-001",
            previous_hash="0" * 64,
            entry_hash="b" * 64,
            signature=b"test-signature",
            signing_key=key,
        )

        entry.description = "Changed"
        with self.assertRaises(TypeError):
            entry.save()
        with self.assertRaises(TypeError):
            WalletTransaction.objects.filter(pk=entry.pk).update(description="Changed")
        with self.assertRaises(TypeError):
            entry.delete()


class WalletServiceTests(TestCase):
    def setUp(self):
        from apps.wallet.models import LedgerSigningKey

        self.user = get_user_model().objects.create_user(
            username="service-user",
            email="service@example.com",
            password="secure-test-password",
        )
        self.wallet = self.user.customer.wallet
        self.key = LedgerSigningKey.objects.create(
            key_id="service-key",
            label="Service test key",
            public_key=b"public-key",
            fingerprint="c" * 64,
        )
        self.signer = lambda payload: b"test-signature"

    def test_credit_is_idempotent(self):
        from apps.wallet.services import credit_wallet

        kwargs = {
            "description": "Manual test top-up",
            "idempotency_key": "service-credit-1",
            "signing_key_id": self.key.pk,
            "signer": self.signer,
        }
        first = credit_wallet(self.wallet.pk, 1000, **kwargs)
        second = credit_wallet(self.wallet.pk, 1000, **kwargs)

        self.wallet.refresh_from_db()
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(self.wallet.balance_cents, 1000)
        self.assertEqual(self.wallet.transactions.count(), 1)

    def test_debit_cannot_spend_reserved_funds(self):
        from apps.wallet.services import InsufficientFunds, credit_wallet, debit_wallet, place_hold

        credit_wallet(
            self.wallet.pk,
            1000,
            description="Top-up",
            idempotency_key="service-credit-2",
            signing_key_id=self.key.pk,
            signer=self.signer,
        )
        place_hold(self.wallet.pk, amount_cents=700, idempotency_key="service-hold-1")

        with self.assertRaises(InsufficientFunds):
            debit_wallet(
                self.wallet.pk,
                400,
                description="Purchase",
                idempotency_key="service-debit-1",
                signing_key_id=self.key.pk,
                signer=self.signer,
            )

    def test_signed_ledger_chain_can_be_verified(self):
        from apps.wallet.services import credit_wallet, verify_wallet_chain

        credit_wallet(
            self.wallet.pk,
            1000,
            description='Chain test top-up',
            idempotency_key='chain-credit-1',
            signing_key_id=self.key.pk,
            signer=self.signer,
        )
        self.assertTrue(
            verify_wallet_chain(
                self.wallet.pk,
                verifier=lambda public_key, payload, signature: signature == b'test-signature',
            )
        )

    def test_capturing_hold_creates_debit_and_releases_reservation(self):
        from apps.wallet.services import capture_hold, credit_wallet, place_hold
        from apps.wallet.models import WalletHold

        credit_wallet(
            self.wallet.pk,
            1000,
            description="Top-up",
            idempotency_key="service-credit-3",
            signing_key_id=self.key.pk,
            signer=self.signer,
        )
        hold = place_hold(self.wallet.pk, amount_cents=300, idempotency_key="service-hold-2")
        entry = capture_hold(hold.pk, signing_key_id=self.key.pk, signer=self.signer)

        self.wallet.refresh_from_db()
        hold.refresh_from_db()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.amount_cents, -300)
        self.assertEqual(self.wallet.balance_cents, 700)
        self.assertEqual(hold.status, WalletHold.Status.CAPTURED)
        self.assertEqual(self.wallet.available_balance_cents, 700)
