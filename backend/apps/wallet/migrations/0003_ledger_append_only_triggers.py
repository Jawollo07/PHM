from django.db import migrations


SQLITE_CREATE = """
CREATE TRIGGER wallet_transactions_reject_update
BEFORE UPDATE ON wallet_transactions
BEGIN
    SELECT RAISE(ABORT, 'Wallet transactions are append-only.');
END;
CREATE TRIGGER wallet_transactions_reject_delete
BEFORE DELETE ON wallet_transactions
BEGIN
    SELECT RAISE(ABORT, 'Wallet transactions are append-only.');
END;
CREATE TRIGGER ledger_checkpoints_reject_update
BEFORE UPDATE ON ledger_checkpoints
BEGIN
    SELECT RAISE(ABORT, 'Ledger checkpoints are append-only.');
END;
CREATE TRIGGER ledger_checkpoints_reject_delete
BEFORE DELETE ON ledger_checkpoints
BEGIN
    SELECT RAISE(ABORT, 'Ledger checkpoints are append-only.');
END;
"""

POSTGRES_CREATE = """
CREATE OR REPLACE FUNCTION phm_reject_immutable_ledger_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% records are append-only.', TG_TABLE_NAME;
END;
$$;

CREATE TRIGGER wallet_transactions_reject_mutation
BEFORE UPDATE OR DELETE ON wallet_transactions
FOR EACH ROW EXECUTE FUNCTION phm_reject_immutable_ledger_mutation();

CREATE TRIGGER ledger_checkpoints_reject_mutation
BEFORE UPDATE OR DELETE ON ledger_checkpoints
FOR EACH ROW EXECUTE FUNCTION phm_reject_immutable_ledger_mutation();
"""


def install_append_only_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == "sqlite":
            for statement in SQLITE_CREATE.strip().split(";"):
                if statement.strip():
                    cursor.execute(statement)
        elif vendor == "postgresql":
            cursor.execute(POSTGRES_CREATE)
        else:
            raise NotImplementedError(
                "PHM ledger append-only triggers currently support SQLite and PostgreSQL only."
            )


def remove_append_only_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == "sqlite":
            for name in (
                "wallet_transactions_reject_update",
                "wallet_transactions_reject_delete",
                "ledger_checkpoints_reject_update",
                "ledger_checkpoints_reject_delete",
            ):
                cursor.execute(f"DROP TRIGGER IF EXISTS {name}")
        elif vendor == "postgresql":
            cursor.execute(
                "DROP TRIGGER IF EXISTS wallet_transactions_reject_mutation "
                "ON wallet_transactions"
            )
            cursor.execute(
                "DROP TRIGGER IF EXISTS ledger_checkpoints_reject_mutation "
                "ON ledger_checkpoints"
            )
            cursor.execute(
                "DROP FUNCTION IF EXISTS phm_reject_immutable_ledger_mutation()"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("wallet", "0002_wallet_manual_adjustment_permission"),
    ]

    operations = [
        migrations.RunPython(
            install_append_only_triggers,
            reverse_code=remove_append_only_triggers,
        ),
    ]
