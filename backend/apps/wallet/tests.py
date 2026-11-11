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
