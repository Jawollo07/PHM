import base64
import fcntl
import hashlib
import json
import os
import stat

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.module_loading import import_string

from .models import LedgerCheckpoint, LedgerSigningKey
from .signing import verify_payload


def _canonical_archive_bytes(payload: dict) -> bytes:
    from .checkpoints import _canonical_bytes

    return _canonical_bytes(payload)


def _trusted_key_snapshot(*, using=None) -> list[dict]:
    keys = LedgerSigningKey.objects.db_manager(using).order_by("key_id")
    snapshot = []
    for key in keys:
        public_key = bytes(key.public_key)
        if len(public_key) != 32:
            raise ValueError(
                f"Ledger signing key {key.key_id} has an invalid Ed25519 public key."
            )
        snapshot.append({
            "key_id": key.key_id,
            "public_key": base64.b64encode(public_key).decode("ascii"),
        })
    return snapshot


def _checkpoint_record_fields(checkpoint):
    from .checkpoints import _checkpoint_payload

    return {
        "archive_version": 1,
        "payload": _checkpoint_payload(checkpoint),
        "checkpoint_hash": checkpoint.checkpoint_hash,
        "signature": base64.b64encode(bytes(checkpoint.signature)).decode("ascii"),
        "public_key": base64.b64encode(
            bytes(checkpoint.signing_key.public_key)
        ).decode("ascii"),
    }


def _record_for_checkpoint(checkpoint, *, using=None):
    return {
        **_checkpoint_record_fields(checkpoint),
        "trusted_keys": _trusted_key_snapshot(using=using),
    }


def _validated_records(data: bytes) -> list[dict]:
    from .checkpoints import _canonical_bytes

    if data and not data.endswith(b"\n"):
        raise ValueError("The checkpoint archive ends with an incomplete record.")

    records = []
    previous_number = None
    previous_hash = None
    for line_number, line in enumerate(data.splitlines(), start=1):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(
                f"Checkpoint archive record {line_number} is not valid JSON."
            ) from exc

        if not isinstance(record, dict) or set(record) != {
            "archive_version",
            "payload",
            "checkpoint_hash",
            "signature",
            "public_key",
            "trusted_keys",
            "archive_signature",
            "archive_signing_key_id",
            "archive_signing_public_key",
        }:
            raise ValueError(f"Checkpoint archive record {line_number} is malformed.")
        if (
            type(record["archive_version"]) is not int
            or record["archive_version"] != 1
            or not isinstance(record["payload"], dict)
            or not isinstance(record["trusted_keys"], list)
        ):
            raise ValueError(f"Checkpoint archive record {line_number} has an unsupported version.")

        payload = record["payload"]
        number = payload.get("checkpoint_number")
        if type(number) is not int or number < 1:
            raise ValueError(f"Checkpoint archive record {line_number} has an invalid number.")
        if previous_number is not None and (
            number != previous_number + 1
            or payload.get("previous_checkpoint_hash") != previous_hash
        ):
            raise ValueError(f"Checkpoint archive chain breaks at record {line_number}.")

        try:
            signature = base64.b64decode(record["signature"], validate=True)
            public_key = base64.b64decode(record["public_key"], validate=True)
            archive_signature = base64.b64decode(
                record["archive_signature"],
                validate=True,
            )
            archive_signing_public_key = base64.b64decode(
                record["archive_signing_public_key"],
                validate=True,
            )
            payload_bytes = _canonical_bytes(payload)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Checkpoint archive record {line_number} has invalid encoded data."
            ) from exc

        checkpoint_hash = hashlib.sha256(payload_bytes).hexdigest()
        if checkpoint_hash != record["checkpoint_hash"]:
            raise ValueError(f"Checkpoint archive record {line_number} has an invalid hash.")
        if len(public_key) != 32 or not verify_payload(public_key, payload_bytes, signature):
            raise ValueError(
                f"Checkpoint archive record {line_number} has an invalid signature."
            )

        trusted_key_ids = []
        trusted_keys_by_id = {}
        for trusted_key in record["trusted_keys"]:
            if not isinstance(trusted_key, dict) or set(trusted_key) != {
                "key_id",
                "public_key",
            }:
                raise ValueError(
                    f"Checkpoint archive record {line_number} has an invalid trusted-key list."
                )
            try:
                trusted_public_key = base64.b64decode(
                    trusted_key["public_key"],
                    validate=True,
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Checkpoint archive record {line_number} has an invalid trusted key."
                ) from exc
            if (
                not isinstance(trusted_key["key_id"], str)
                or not trusted_key["key_id"]
                or len(trusted_public_key) != 32
            ):
                raise ValueError(
                    f"Checkpoint archive record {line_number} has an invalid trusted key."
                )
            trusted_key_ids.append(trusted_key["key_id"])
            trusted_keys_by_id[trusted_key["key_id"]] = trusted_key["public_key"]
        if trusted_key_ids != sorted(set(trusted_key_ids)):
            raise ValueError(
                f"Checkpoint archive record {line_number} has a non-canonical trusted-key list."
            )
        if trusted_keys_by_id.get(payload.get("signing_key_id")) != record["public_key"]:
            raise ValueError(
                f"Checkpoint archive record {line_number} does not trust its signing key."
            )
        if (
            not isinstance(record["archive_signing_key_id"], str)
            or trusted_keys_by_id.get(record["archive_signing_key_id"])
            != record["archive_signing_public_key"]
            or len(archive_signing_public_key) != 32
        ):
            raise ValueError(
                f"Checkpoint archive record {line_number} has an untrusted archive signer."
            )
        archive_payload = {
            key: value for key, value in record.items()
            if key != "archive_signature"
        }
        if not verify_payload(
            archive_signing_public_key,
            _canonical_bytes(archive_payload),
            archive_signature,
        ):
            raise ValueError(
                f"Checkpoint archive record {line_number} has an invalid archive signature."
            )

        previous_number = number
        previous_hash = checkpoint_hash
        records.append(record)
    return records


def _read_archive(path) -> list[dict]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(os.fspath(path), flags)
    except FileNotFoundError:
        return []

    try:
        file_info = os.fstat(descriptor)
        if not stat.S_ISREG(file_info.st_mode):
            raise ValueError("The checkpoint archive must be a regular file.")
        if stat.S_IMODE(file_info.st_mode) & 0o077:
            raise ValueError("The checkpoint archive must have permissions 0600.")
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        with os.fdopen(descriptor, "rb") as archive:
            descriptor = -1
            return _validated_records(archive.read())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _archive_path(archive_path=None):
    path = archive_path or settings.WALLET_LEDGER_CHECKPOINT_ARCHIVE_FILE
    if not path:
        raise ImproperlyConfigured(
            "WALLET_LEDGER_CHECKPOINT_ARCHIVE_FILE must point to a protected "
            "checkpoint archive outside the database."
        )
    return path


def verify_checkpoint_archive(*, archive_path=None, using=None) -> bool:
    """Verify external archive signatures and require an exact match to the DB head."""
    from .checkpoints import _checkpoint_payload, verify_ledger_checkpoint

    path = _archive_path(archive_path)
    records = _read_archive(path)
    checkpoints = LedgerCheckpoint.objects.db_manager(using)
    latest = checkpoints.select_related("signing_key").order_by(
        "-checkpoint_number"
    ).first()
    if not records:
        return latest is None
    if latest is None or latest.checkpoint_number != records[-1]["payload"]["checkpoint_number"]:
        return False

    for record in records:
        checkpoint = checkpoints.select_related("signing_key").filter(
            checkpoint_number=record["payload"]["checkpoint_number"]
        ).first()
        if checkpoint is None:
            return False
        checkpoint_fields = _checkpoint_record_fields(checkpoint)
        if (
            any(record.get(key) != value for key, value in checkpoint_fields.items())
            or _checkpoint_payload(checkpoint) != record["payload"]
        ):
            return False

    if records[-1]["trusted_keys"] != _trusted_key_snapshot(using=using):
        return False

    return verify_ledger_checkpoint(
        latest.pk,
        verifier=verify_payload,
        using=using,
    )


def sync_checkpoint_archive(*, archive_path=None, using=None) -> int:
    """Append a valid, committed DB suffix after an interrupted archive write."""
    from .checkpoints import _checkpoint_payload, verify_ledger_checkpoint
    from .services import verify_wallet_chain
    from .models import Wallet

    path = _archive_path(archive_path)
    records = _read_archive(path)
    if not records:
        raise ValueError(
            "The archive has no trusted baseline. Run bootstrap_checkpoint_archive first."
        )

    checkpoints = LedgerCheckpoint.objects.db_manager(using).select_related(
        "signing_key"
    )
    latest = checkpoints.order_by("-checkpoint_number").first()
    archived_number = records[-1]["payload"]["checkpoint_number"]
    if latest is None or latest.checkpoint_number < archived_number:
        raise ValueError(
            "The database is behind the external archive; refusing to sync a rollback."
        )

    for record in records:
        checkpoint = checkpoints.filter(
            checkpoint_number=record["payload"]["checkpoint_number"]
        ).first()
        if checkpoint is None:
            raise ValueError("The external archive does not match the database.")
        expected = _checkpoint_record_fields(checkpoint)
        if (
            any(record.get(key) != value for key, value in expected.items())
            or _checkpoint_payload(checkpoint) != record["payload"]
        ):
            raise ValueError("The external archive does not match the database.")

    if records[-1]["trusted_keys"] != _trusted_key_snapshot(using=using):
        raise ValueError(
            "The database signing-key registry differs from the external archive."
        )

    for wallet in Wallet.objects.db_manager(using).order_by("pk").iterator():
        if not verify_wallet_chain(wallet.pk, verify_payload, using=using):
            raise ValueError(
                f"Wallet {wallet.pk} failed verification; the archive was not synced."
            )
    if not verify_ledger_checkpoint(
        latest.pk,
        verifier=verify_payload,
        compare_current_state=True,
        using=using,
    ):
        raise ValueError(
            "The latest database checkpoint or ledger state failed verification."
        )

    missing = list(
        checkpoints.filter(checkpoint_number__gt=archived_number).order_by(
            "checkpoint_number"
        )
    )
    for checkpoint in missing:
        append_checkpoint_to_archive(
            checkpoint.pk,
            archive_path=path,
            using=using,
        )
    if not verify_checkpoint_archive(archive_path=path, using=using):
        raise ValueError("The external checkpoint archive failed verification after sync.")
    return len(missing)


def append_checkpoint_to_archive(
    checkpoint_id,
    *,
    archive_path=None,
    using=None,
    allow_baseline=False,
) -> None:
    """Append one committed checkpoint, rejecting gaps, rewrites and rollbacks."""
    path = _archive_path(archive_path)
    checkpoint = (
        LedgerCheckpoint.objects.db_manager(using)
        .select_related("signing_key")
        .get(pk=checkpoint_id)
    )
    record = _record_for_checkpoint(checkpoint, using=using)
    archive_signing_key_id = settings.WALLET_LEDGER_KEY_ID
    signer_path = settings.WALLET_LEDGER_SIGNER
    if not archive_signing_key_id or not signer_path:
        raise ImproperlyConfigured(
            "WALLET_LEDGER_KEY_ID and WALLET_LEDGER_SIGNER are required "
            "to sign external checkpoint archive records."
        )
    archive_signing_key = LedgerSigningKey.objects.db_manager(using).get(
        key_id=archive_signing_key_id,
        status=LedgerSigningKey.Status.ACTIVE,
    )
    record["archive_signing_key_id"] = archive_signing_key.key_id
    record["archive_signing_public_key"] = base64.b64encode(
        bytes(archive_signing_key.public_key)
    ).decode("ascii")
    archive_signature = import_string(signer_path)(_canonical_archive_bytes(record))
    archive_public_key = bytes(archive_signing_key.public_key)
    if (
        not isinstance(archive_signature, bytes)
        or not verify_payload(
            archive_public_key,
            _canonical_archive_bytes(record),
            archive_signature,
        )
    ):
        raise ValueError(
            "The archive signing provider does not match its registered public key."
        )
    record["archive_signature"] = base64.b64encode(archive_signature).decode("ascii")
    line = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8") + b"\n"
    _validated_records(line)

    flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.fspath(path), flags, 0o600)
    try:
        file_info = os.fstat(descriptor)
        if not stat.S_ISREG(file_info.st_mode):
            raise ValueError("The checkpoint archive must be a regular file.")
        if stat.S_IMODE(file_info.st_mode) & 0o077:
            raise ValueError("The checkpoint archive must have permissions 0600.")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks = []
        while chunk := os.read(descriptor, 65536):
            chunks.append(chunk)
        records = _validated_records(b"".join(chunks))
        if records:
            last = records[-1]
            if last == record:
                return
            if last["trusted_keys"] != _trusted_key_snapshot(using=using):
                raise ValueError(
                    "The database signing-key registry changed after the external "
                    "checkpoint baseline."
                )
            if (
                checkpoint.checkpoint_number
                != last["payload"]["checkpoint_number"] + 1
                or checkpoint.previous_checkpoint_hash != last["checkpoint_hash"]
            ):
                raise ValueError(
                    "The checkpoint archive head does not match the checkpoint being appended."
                )
        elif not allow_baseline and (
            checkpoint.checkpoint_number != 1
            or checkpoint.previous_checkpoint_hash != "0" * 64
        ):
            raise ValueError(
                "The archive has no trusted baseline. Run bootstrap_checkpoint_archive "
                "while the current database is verified."
            )

        written = 0
        while written < len(line):
            count = os.write(descriptor, line[written:])
            if count <= 0:
                raise OSError("Could not write a complete checkpoint archive record.")
            written += count
        os.fsync(descriptor)
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def bootstrap_checkpoint_archive(*, archive_path=None, using=None):
    """Establish a trusted external baseline from the currently verified DB head."""
    from .checkpoints import verify_ledger_checkpoint
    from .services import verify_wallet_chain

    path = _archive_path(archive_path)
    if _read_archive(path):
        raise ValueError("The checkpoint archive is not empty; refusing to replace it.")

    checkpoints = LedgerCheckpoint.objects.db_manager(using)
    checkpoint = checkpoints.select_related("signing_key").order_by(
        "-checkpoint_number"
    ).first()
    if checkpoint is None:
        raise ValueError("Create a signed database checkpoint before bootstrapping the archive.")

    from .models import Wallet

    wallets = Wallet.objects.db_manager(using).order_by("pk")
    for wallet in wallets.iterator():
        if not verify_wallet_chain(wallet.pk, verify_payload, using=using):
            raise ValueError(
                f"Wallet {wallet.pk} failed verification; the archive was not bootstrapped."
            )
    if not verify_ledger_checkpoint(
        checkpoint.pk,
        verifier=verify_payload,
        compare_current_state=True,
        using=using,
    ):
        raise ValueError(
            "The database checkpoint does not match the current ledger; "
            "the archive was not bootstrapped."
        )

    append_checkpoint_to_archive(
        checkpoint.pk,
        archive_path=path,
        using=using,
        allow_baseline=True,
    )
    return checkpoint
