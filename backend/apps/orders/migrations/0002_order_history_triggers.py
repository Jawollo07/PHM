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
    """CREATE TRIGGER orders_reject_immutable_fields
    BEFORE UPDATE ON orders
    WHEN NEW.customer_id IS NOT OLD.customer_id
      OR NEW.currency IS NOT OLD.currency
      OR NEW.total_cents IS NOT OLD.total_cents
      OR NEW.idempotency_key IS NOT OLD.idempotency_key
      OR NEW.created_at IS NOT OLD.created_at
      OR (OLD.wallet_hold_id IS NOT NULL AND NEW.wallet_hold_id IS NOT OLD.wallet_hold_id)
      OR (OLD.paid_transaction_id IS NOT NULL AND NEW.paid_transaction_id IS NOT OLD.paid_transaction_id)
      OR (OLD.paid_at IS NOT NULL AND NEW.paid_at IS NOT OLD.paid_at)
    BEGIN
        SELECT RAISE(ABORT, 'Order ownership, totals and payment references are immutable.');
    END""",
    """CREATE TRIGGER orders_reject_invalid_transition
    BEFORE UPDATE ON orders
    WHEN NEW.status IS NOT OLD.status
      AND NOT (
          (OLD.status = 'pending_payment' AND NEW.status IN ('paid', 'cancelled', 'failed'))
          OR (OLD.status = 'paid' AND NEW.status IN ('provisioning', 'failed'))
          OR (OLD.status = 'provisioning' AND NEW.status IN ('active', 'failed'))
      )
    BEGIN
        SELECT RAISE(ABORT, 'Invalid order state transition.');
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
    """CREATE OR REPLACE FUNCTION phm_guard_order_update()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $
    BEGIN
        IF NEW.customer_id IS DISTINCT FROM OLD.customer_id
           OR NEW.currency IS DISTINCT FROM OLD.currency
           OR NEW.total_cents IS DISTINCT FROM OLD.total_cents
           OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR (OLD.wallet_hold_id IS NOT NULL AND NEW.wallet_hold_id IS DISTINCT FROM OLD.wallet_hold_id)
           OR (OLD.paid_transaction_id IS NOT NULL AND NEW.paid_transaction_id IS DISTINCT FROM OLD.paid_transaction_id)
           OR (OLD.paid_at IS NOT NULL AND NEW.paid_at IS DISTINCT FROM OLD.paid_at) THEN
            RAISE EXCEPTION 'Order ownership, totals and payment references are immutable.';
        END IF;
        IF NEW.status IS DISTINCT FROM OLD.status
           AND NOT (
               (OLD.status = 'pending_payment' AND NEW.status IN ('paid', 'cancelled', 'failed'))
               OR (OLD.status = 'paid' AND NEW.status IN ('provisioning', 'failed'))
               OR (OLD.status = 'provisioning' AND NEW.status IN ('active', 'failed'))
           ) THEN
            RAISE EXCEPTION 'Invalid order state transition.';
        END IF;
        RETURN NEW;
    END;
    $""",
    """CREATE TRIGGER orders_guard_update
    BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION phm_guard_order_update()""",
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
                "orders_reject_immutable_fields",
                "orders_reject_invalid_transition",
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
                "DROP TRIGGER IF EXISTS orders_guard_update ON orders"
            )
            cursor.execute(
                "DROP FUNCTION IF EXISTS phm_guard_order_update()"
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
