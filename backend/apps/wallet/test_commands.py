from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core.management import call_command, CommandError
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from apps.auth.models import User
from apps.wallet.checkpoints import create_ledger_checkpoint
from apps.wallet.models import LedgerSigningKey, WalletTransaction
from apps.wallet.services import capture_hold, credit_wallet, place_hold


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

    def test_register_signing_key_uses_protected_pem_file(self):
        from django.test import override_settings

        self.key.status = LedgerSigningKey.Status.RETIRED
        self.key.save(update_fields=["status"])
        private_key = Ed25519PrivateKey.generate()
        pem_data = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        expected_public_key = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        with TemporaryDirectory() as directory:
            path = Path(directory) / "wallet-ledger.pem"
            path.write_bytes(pem_data)
            path.chmod(0o600)
            with override_settings(
                WALLET_LEDGER_KEY_ID="file-backed-test-key",
                WALLET_LEDGER_PRIVATE_KEY_FILE=str(path),
                WALLET_LEDGER_PRIVATE_KEY_B64="",
                WALLET_LEDGER_PRIVATE_KEY_HEX="",
            ):
                call_command("register_wallet_signing_key")

        registered_key = LedgerSigningKey.objects.get(key_id="file-backed-test-key")
        self.assertEqual(bytes(registered_key.public_key), expected_public_key)

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
            metadata={},
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

    def test_checkpoint_command_creates_checkpoint_after_verification(self):
        import base64

        from django.test import override_settings

        raw_private_key = self.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with override_settings(
            WALLET_LEDGER_KEY_ID=self.key.key_id,
            WALLET_LEDGER_SIGNER="apps.wallet.signing.sign_payload",
            WALLET_LEDGER_PRIVATE_KEY_FILE="",
            WALLET_LEDGER_PRIVATE_KEY_B64=base64.b64encode(raw_private_key).decode("ascii"),
            WALLET_LEDGER_PRIVATE_KEY_HEX="",
        ):
            call_command("checkpoint_ledger")

        self.assertEqual(self.key.checkpoints.count(), 1)

    def test_checkpoint_command_anchors_valid_ledger_changes(self):
        import base64

        from django.test import override_settings
        from apps.wallet.services import credit_wallet

        raw_private_key = self.private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        create_ledger_checkpoint(
            signing_key_id=self.key.pk,
            signer=self.private_key.sign,
        )
        new_user = User.objects.create_user(
            username="new-wallet-after-checkpoint",
            email="new-wallet-after-checkpoint@example.com",
            password="secure-test-password",
        )
        credit_wallet(
            new_user.customer.wallet.pk,
            2500,
            description="Post-checkpoint credit",
            idempotency_key="post-checkpoint-credit-1",
            signing_key_id=self.key.pk,
            signer=self.private_key.sign,
            metadata={},
        )

        with self.assertRaisesRegex(
            CommandError,
            "current ledger snapshot verification failed",
        ):
            call_command("verify_ledger")

        with override_settings(
            WALLET_LEDGER_KEY_ID=self.key.key_id,
            WALLET_LEDGER_SIGNER="apps.wallet.signing.sign_payload",
            WALLET_LEDGER_PRIVATE_KEY_FILE="",
            WALLET_LEDGER_PRIVATE_KEY_B64=base64.b64encode(raw_private_key).decode("ascii"),
            WALLET_LEDGER_PRIVATE_KEY_HEX="",
        ):
            call_command("checkpoint_ledger")

        self.assertEqual(self.key.checkpoints.count(), 2)
        call_command("verify_ledger")

    def test_auto_checkpoint_runs_after_each_new_transaction_not_replay(self):
        from django.test import override_settings

        from apps.wallet.checkpoint_archive import verify_checkpoint_archive
        from apps.wallet.checkpoints import verify_ledger_checkpoint
        from apps.wallet.signing import verify_payload

        pem_data = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "wallet-ledger.pem"
            path.write_bytes(pem_data)
            path.chmod(0o600)
            with override_settings(
                WALLET_LEDGER_AUTO_CHECKPOINT=True,
                WALLET_LEDGER_KEY_ID=self.key.key_id,
                WALLET_LEDGER_SIGNER="apps.wallet.signing.sign_payload",
                WALLET_LEDGER_PRIVATE_KEY_FILE=str(path),
                WALLET_LEDGER_PRIVATE_KEY_B64="",
                WALLET_LEDGER_PRIVATE_KEY_HEX="",
                WALLET_LEDGER_CHECKPOINT_ARCHIVE_FILE=str(
                    Path(directory) / "checkpoints.jsonl"
                ),
            ):
                wallet_id = self.user.customer.wallet.pk
                credit_args = {
                    "description": "Automatically checkpointed credit",
                    "idempotency_key": "auto-checkpoint-credit-1",
                    "signing_key_id": self.key.pk,
                    "signer": self.private_key.sign,
                    "metadata": {},
                }
                with self.captureOnCommitCallbacks(execute=True):
                    credit_wallet(wallet_id, 100, **credit_args)
                self.assertEqual(self.key.checkpoints.count(), 1)
                self.assertEqual(
                    self.key.checkpoints.get().transaction_count,
                    1,
                )

                credit_wallet(wallet_id, 100, **credit_args)
                self.assertEqual(self.key.checkpoints.count(), 1)
                self.assertEqual(WalletTransaction.objects.count(), 1)

                with self.captureOnCommitCallbacks(execute=True):
                    credit_wallet(
                        wallet_id,
                        200,
                        description="Automatically checkpointed credit",
                        idempotency_key="auto-checkpoint-credit-2",
                        signing_key_id=self.key.pk,
                        signer=self.private_key.sign,
                        metadata={},
                    )
                self.assertEqual(self.key.checkpoints.count(), 2)
                checkpoint = self.key.checkpoints.order_by(
                    "-checkpoint_number"
                ).first()
                self.assertEqual(checkpoint.transaction_count, 2)
                self.assertTrue(
                    verify_ledger_checkpoint(
                        checkpoint.pk,
                        verifier=verify_payload,
                        compare_current_state=True,
                    )
                )
                self.assertTrue(
                    verify_checkpoint_archive(
                        archive_path=str(Path(directory) / "checkpoints.jsonl")
                    )
                )

    def test_new_wallet_is_included_in_automatic_checkpoint(self):
        from django.test import override_settings

        from apps.wallet.checkpoint_archive import verify_checkpoint_archive
        from apps.wallet.checkpoints import verify_ledger_checkpoint
        from apps.wallet.signing import verify_payload

        pem_data = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "wallet-ledger.pem"
            path.write_bytes(pem_data)
            path.chmod(0o600)
            with override_settings(
                WALLET_LEDGER_AUTO_CHECKPOINT=True,
                WALLET_LEDGER_KEY_ID=self.key.key_id,
                WALLET_LEDGER_SIGNER="apps.wallet.signing.sign_payload",
                WALLET_LEDGER_PRIVATE_KEY_FILE=str(path),
                WALLET_LEDGER_PRIVATE_KEY_B64="",
                WALLET_LEDGER_PRIVATE_KEY_HEX="",
                WALLET_LEDGER_CHECKPOINT_ARCHIVE_FILE=str(
                    Path(directory) / "checkpoints.jsonl"
                ),
            ):
                with self.captureOnCommitCallbacks(execute=True):
                    User.objects.create_user(
                        username="auto-checkpoint-new-wallet",
                        email="auto-checkpoint-new-wallet@example.com",
                        password="secure-test-password",
                    )
                checkpoint = self.key.checkpoints.get()
                self.assertEqual(checkpoint.wallet_count, 2)
                self.assertEqual(checkpoint.transaction_count, 0)
                self.assertTrue(
                    verify_ledger_checkpoint(
                        checkpoint.pk,
                        verifier=verify_payload,
                        compare_current_state=True,
                    )
                )
                self.assertTrue(
                    verify_checkpoint_archive(
                        archive_path=str(Path(directory) / "checkpoints.jsonl")
                    )
                )

    def test_captured_hold_creates_checkpoint_for_wallet_debit(self):
        from django.test import override_settings

        from apps.wallet.checkpoint_archive import verify_checkpoint_archive
        from apps.wallet.checkpoints import verify_ledger_checkpoint
        from apps.wallet.signing import verify_payload

        pem_data = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "wallet-ledger.pem"
            path.write_bytes(pem_data)
            path.chmod(0o600)
            with override_settings(
                WALLET_LEDGER_AUTO_CHECKPOINT=True,
                WALLET_LEDGER_KEY_ID=self.key.key_id,
                WALLET_LEDGER_SIGNER="apps.wallet.signing.sign_payload",
                WALLET_LEDGER_PRIVATE_KEY_FILE=str(path),
                WALLET_LEDGER_PRIVATE_KEY_B64="",
                WALLET_LEDGER_PRIVATE_KEY_HEX="",
                WALLET_LEDGER_CHECKPOINT_ARCHIVE_FILE=str(
                    Path(directory) / "checkpoints.jsonl"
                ),
            ):
                wallet_id = self.user.customer.wallet.pk
                with self.captureOnCommitCallbacks(execute=True):
                    credit_wallet(
                        wallet_id,
                        500,
                        description="Fund wallet before hold capture",
                        idempotency_key="auto-checkpoint-hold-fund-1",
                        signing_key_id=self.key.pk,
                        signer=self.private_key.sign,
                        metadata={},
                    )
                hold = place_hold(
                    wallet_id,
                    amount_cents=200,
                    idempotency_key="auto-checkpoint-hold-1",
                    metadata={},
                )
                with self.captureOnCommitCallbacks(execute=True):
                    capture_hold(
                        hold.pk,
                        signing_key_id=self.key.pk,
                        signer=self.private_key.sign,
                    )
                self.assertEqual(self.key.checkpoints.count(), 2)
                self.assertEqual(WalletTransaction.objects.count(), 2)
                checkpoint = self.key.checkpoints.order_by(
                    "-checkpoint_number"
                ).first()
                self.assertEqual(checkpoint.transaction_count, 2)
                self.assertTrue(
                    verify_ledger_checkpoint(
                        checkpoint.pk,
                        verifier=verify_payload,
                        compare_current_state=True,
                    )
                )
                self.assertTrue(
                    verify_checkpoint_archive(
                        archive_path=str(Path(directory) / "checkpoints.jsonl")
                    )
                )

    def test_checkpoint_failure_rolls_back_wallet_transaction(self):
        from django.test import override_settings

        wallet = self.user.customer.wallet
        with TemporaryDirectory() as directory:
            with override_settings(
                WALLET_LEDGER_AUTO_CHECKPOINT=True,
                WALLET_LEDGER_KEY_ID=self.key.key_id,
                WALLET_LEDGER_SIGNER="apps.wallet.signing.sign_payload",
                WALLET_LEDGER_PRIVATE_KEY_FILE="/no/such/wallet-ledger.pem",
                WALLET_LEDGER_PRIVATE_KEY_B64="",
                WALLET_LEDGER_PRIVATE_KEY_HEX="",
                WALLET_LEDGER_CHECKPOINT_ARCHIVE_FILE=str(
                    Path(directory) / "checkpoints.jsonl"
                ),
            ):
                with self.assertRaises(ImproperlyConfigured):
                    credit_wallet(
                        wallet.pk,
                        100,
                        description="Must roll back without a checkpoint",
                        idempotency_key="auto-checkpoint-failure-1",
                        signing_key_id=self.key.pk,
                        signer=self.private_key.sign,
                        metadata={},
                    )

        wallet.refresh_from_db()
        self.assertEqual(wallet.balance_cents, 0)
        self.assertEqual(WalletTransaction.objects.count(), 0)
        self.assertEqual(self.key.checkpoints.count(), 0)

    def test_external_archive_detects_database_tampering_and_rollback(self):
        from django.db import DatabaseError, connection, transaction
        from django.test import override_settings

        from apps.wallet.checkpoint_archive import verify_checkpoint_archive

        checkpoint = create_ledger_checkpoint(
            signing_key_id=self.key.pk,
            signer=self.private_key.sign,
        )
        with TemporaryDirectory() as directory:
            archive_path = str(Path(directory) / "checkpoints.jsonl")
            private_key_path = Path(directory) / "wallet-ledger.pem"
            private_key_path.write_bytes(
                self.private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption(),
                )
            )
            private_key_path.chmod(0o600)
            with override_settings(
                WALLET_LEDGER_CHECKPOINT_ARCHIVE_FILE=archive_path,
                WALLET_LEDGER_KEY_ID=self.key.key_id,
                WALLET_LEDGER_SIGNER="apps.wallet.signing.sign_payload",
                WALLET_LEDGER_PRIVATE_KEY_FILE=str(private_key_path),
                WALLET_LEDGER_PRIVATE_KEY_B64="",
                WALLET_LEDGER_PRIVATE_KEY_HEX="",
            ):
                call_command("bootstrap_checkpoint_archive")
                self.assertTrue(verify_checkpoint_archive())

                rogue_key = Ed25519PrivateKey.generate().public_key().public_bytes(
                    encoding=serialization.Encoding.Raw,
                    format=serialization.PublicFormat.Raw,
                )
                rogue_registry_entry = LedgerSigningKey.objects.create(
                    key_id="untrusted-added-key",
                    label="Untrusted added key",
                    public_key=rogue_key,
                    fingerprint="e" * 64,
                    status=LedgerSigningKey.Status.ACTIVE,
                )
                self.assertFalse(verify_checkpoint_archive())
                rogue_registry_entry.delete()
                self.assertTrue(verify_checkpoint_archive())

                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE wallets SET balance_cents = 1 WHERE id = %s",
                        [self.user.customer.wallet.pk.hex],
                    )
                with self.assertRaises(CommandError):
                    call_command("verify_ledger")
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE wallets SET balance_cents = 0 WHERE id = %s",
                        [self.user.customer.wallet.pk.hex],
                    )

                try:
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "DELETE FROM ledger_checkpoints WHERE id = %s",
                                [checkpoint.pk.hex],
                            )
                except DatabaseError:
                    self.assertTrue(verify_checkpoint_archive())
                else:
                    self.assertFalse(verify_checkpoint_archive())

    def test_external_archive_syncs_a_committed_checkpoint_suffix(self):
        from django.test import override_settings

        from apps.wallet.checkpoint_archive import verify_checkpoint_archive

        first = create_ledger_checkpoint(
            signing_key_id=self.key.pk,
            signer=self.private_key.sign,
        )
        pem_data = self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "wallet-ledger.pem"
            path.write_bytes(pem_data)
            path.chmod(0o600)
            archive_path = str(Path(directory) / "checkpoints.jsonl")
            with override_settings(
                WALLET_LEDGER_KEY_ID=self.key.key_id,
                WALLET_LEDGER_SIGNER="apps.wallet.signing.sign_payload",
                WALLET_LEDGER_PRIVATE_KEY_FILE=str(path),
                WALLET_LEDGER_PRIVATE_KEY_B64="",
                WALLET_LEDGER_PRIVATE_KEY_HEX="",
                WALLET_LEDGER_CHECKPOINT_ARCHIVE_FILE=archive_path,
            ):
                call_command("bootstrap_checkpoint_archive")
                with self.captureOnCommitCallbacks(execute=False):
                    second = create_ledger_checkpoint(
                        signing_key_id=self.key.pk,
                        signer=self.private_key.sign,
                    )

                self.assertFalse(verify_checkpoint_archive())
                output = StringIO()
                call_command("sync_checkpoint_archive", stdout=output)
                self.assertIn("appended 1 checkpoint(s)", output.getvalue())
                self.assertTrue(verify_checkpoint_archive())
                self.assertEqual(second.checkpoint_number, first.checkpoint_number + 1)
