from django.db import migrations


SQLITE_STATEMENTS = (
    """CREATE TRIGGER order_items_reject_update
    BEFORE UPDATE ON order_items
    BEGIN
        SELECT RAISE(ABORT, 'Order item snapshots are immutable.');
    END""",
    """CREATE TRIGGER order_items_reject_delete
    BEFORE DELETE ON order_items
    BEGIN
        SELECT RAISE(ABORT, 'Order item snapshots are immutable.');
    END""",
    """CREATE TRIGGER orders_reject_delete
    BEFORE DELETE ON orders
    BEGIN
        SELECT RAISE(ABORT, 'Orders are retained permanently.');
    END""",
)

POSTGRES_STATEMENTS = (
    """CREATE OR REPLACE FUNCTION phm_reject_order_history_mutation()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $$
    BEGIN
        RAISE EXCEPTION '% records are immutable.', TG_TABLE_NAME;
    END;
    $$""",
    """CREATE TRIGGER order_items_reject_mutation
    BEFORE UPDATE OR DELETE ON order_items
    FOR EACH ROW EXECUTE FUNCTION phm_reject_order_history_mutation()""",
    """CREATE TRIGGER orders_reject_delete
    BEFORE DELETE ON orders
    FOR EACH ROW EXECUTE FUNCTION phm_reject_order_history_mutation()""",
)


def install_order_history_triggers(apps, schema_editor):
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
                "PHM order history triggers currently support SQLite and PostgreSQL only."
            )


def remove_order_history_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == "sqlite":
            for name in (
                "order_items_reject_update",
                "order_items_reject_delete",
                "orders_reject_delete",
            ):
                cursor.execute(f"DROP TRIGGER IF EXISTS {name}")
        elif vendor == "postgresql":
            cursor.execute(
                "DROP TRIGGER IF EXISTS order_items_reject_mutation ON order_items"
            )
            cursor.execute(
                "DROP TRIGGER IF EXISTS orders_reject_delete ON orders"
            )
            cursor.execute(
                "DROP FUNCTION IF EXISTS phm_reject_order_history_mutation()"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(
            install_order_history_triggers,
            reverse_code=remove_order_history_triggers,
        ),
    ]
