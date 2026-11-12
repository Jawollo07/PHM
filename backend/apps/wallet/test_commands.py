from io import StringIO

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core.management import call_command, CommandError
from django.test import TestCase

from apps.auth.models import User
from apps.wallet.checkpoints import create_ledger_checkpoint
from apps.wallet.models import LedgerSigningKey
from apps.wallet.services import credit_wallet


class VerifyLedgerCommandTests(TestCase):
    def setUp(self):
        self.private_key = Ed25519PrivateKey.generate()
        public_key = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.user = User.objects.create_user(
            username="ledger-check-user",
            email="ledger-check@example.com",
            password="secure-test-password",
        )
        self.key = LedgerSigningKey.objects.create(
            key_id="ledger-command-test-key",
            label="Ledger command test key",
            public_key=public_key,
            fingerprint="a" * 64,
            status=LedgerSigningKey.Status.ACTIVE,
        )

    def test_command_requires_a_signed_checkpoint_by_default(self):
        with self.assertRaisesRegex(CommandError, "No signed ledger checkpoint"):
            call_command("verify_ledger")

    def test_command_verifies_wallet_chain_and_signed_checkpoint(self):
        credit_wallet(
            self.user.customer.wallet.pk,
            1234,
            description="Integrity command fixture",
            idempotency_key="ledger-command-credit-1",
            signing_key_id=self.key.pk,
            signer=self.private_key.sign,
        )
        create_ledger_checkpoint(
            signing_key_id=self.key.pk,
            signer=self.private_key.sign,
        )
        call_command("verify_ledger")

    def test_allow_unanchored_reports_preliminary_verification(self):
        output = StringIO()
        call_command("verify_ledger", "--allow-unanchored", stdout=output)
        self.assertIn("without a signed checkpoint", output.getvalue())
