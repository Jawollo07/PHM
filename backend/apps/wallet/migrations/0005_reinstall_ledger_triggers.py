from django.db import migrations


SQLITE_STATEMENTS = (
    "DROP TRIGGER IF EXISTS wallet_transactions_reject_update",
    "DROP TRIGGER IF EXISTS wallet_transactions_reject_delete",
    """CREATE TRIGGER wallet_transactions_reject_update
    BEFORE UPDATE ON wallet_transactions
    BEGIN
        SELECT RAISE(ABORT, 'Wallet transactions are append-only.');
    END""",
    """CREATE TRIGGER wallet_transactions_reject_delete
    BEFORE DELETE ON wallet_transactions
    BEGIN
        SELECT RAISE(ABORT, 'Wallet transactions are append-only.');
    END""",
    "DROP TRIGGER IF EXISTS ledger_checkpoints_reject_update",
    "DROP TRIGGER IF EXISTS ledger_checkpoints_reject_delete",
    """CREATE TRIGGER ledger_checkpoints_reject_update
    BEFORE UPDATE ON ledger_checkpoints
    BEGIN
        SELECT RAISE(ABORT, 'Ledger checkpoints are append-only.');
    END""",
    """CREATE TRIGGER ledger_checkpoints_reject_delete
    BEFORE DELETE ON ledger_checkpoints
    BEGIN
        SELECT RAISE(ABORT, 'Ledger checkpoints are append-only.');
    END""",
)

POSTGRES_STATEMENTS = (
    """CREATE OR REPLACE FUNCTION phm_reject_immutable_ledger_mutation()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RAISE EXCEPTION '% records are append-only.', TG_TABLE_NAME;
    END;
    $$""",
    "DROP TRIGGER IF EXISTS wallet_transactions_reject_mutation ON wallet_transactions",
    """CREATE TRIGGER wallet_transactions_reject_mutation
    BEFORE UPDATE OR DELETE ON wallet_transactions
    FOR EACH ROW EXECUTE FUNCTION phm_reject_immutable_ledger_mutation()""",
    "DROP TRIGGER IF EXISTS ledger_checkpoints_reject_mutation ON ledger_checkpoints",
    """CREATE TRIGGER ledger_checkpoints_reject_mutation
    BEFORE UPDATE OR DELETE ON ledger_checkpoints
    FOR EACH ROW EXECUTE FUNCTION phm_reject_immutable_ledger_mutation()""",
)


def reinstall_ledger_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == "sqlite":
            for statement in SQLITE_STATEMENTS:
                cursor.execute(statement)
        elif vendor == "postgresql":
            for statement in POSTGRES_STATEMENTS:
                cursor.execute(statement)
        else:
            raise NotImplementedError(
                "PHM ledger append-only triggers support SQLite and PostgreSQL only."
            )


class Migration(migrations.Migration):
    dependencies = [
        ("wallet", "0004_remove_wallethold_wallet_hold_capture_consistent_and_more"),
    ]

    operations = [
        migrations.RunPython(reinstall_ledger_triggers, migrations.RunPython.noop),
    ]
