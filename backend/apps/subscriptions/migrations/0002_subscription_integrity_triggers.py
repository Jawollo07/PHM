from django.db import migrations


SQLITE_STATEMENTS = (
    """CREATE TRIGGER subscriptions_reject_delete
    BEFORE DELETE ON subscriptions
    BEGIN
        SELECT RAISE(ABORT, 'Subscription history is immutable.');
    END""",
    """CREATE TRIGGER subscriptions_reject_terms_update
    BEFORE UPDATE ON subscriptions
    WHEN NEW.customer_id IS NOT OLD.customer_id
      OR NEW.order_item_id IS NOT OLD.order_item_id
      OR NEW.plan_id IS NOT OLD.plan_id
      OR NEW.currency IS NOT OLD.currency
      OR NEW.price_cents IS NOT OLD.price_cents
      OR NEW.billing_interval_unit IS NOT OLD.billing_interval_unit
      OR NEW.billing_interval_count IS NOT OLD.billing_interval_count
      OR NEW.created_at IS NOT OLD.created_at
      OR (OLD.cancelled_at IS NOT NULL AND NEW.cancelled_at IS NOT OLD.cancelled_at)
    BEGIN
        SELECT RAISE(ABORT, 'Subscription ownership and billing terms are immutable.');
    END""",
    """CREATE TRIGGER subscriptions_reject_invalid_transition
    BEFORE UPDATE ON subscriptions
    WHEN NEW.status IS NOT OLD.status
      AND NOT (
          (OLD.status = 'active' AND NEW.status IN ('past_due', 'suspended', 'cancelled', 'expired'))
          OR (OLD.status = 'past_due' AND NEW.status IN ('active', 'suspended', 'cancelled', 'expired'))
          OR (OLD.status = 'suspended' AND NEW.status IN ('active', 'cancelled', 'expired'))
      )
    BEGIN
        SELECT RAISE(ABORT, 'Invalid subscription state transition.');
    END""",
)

POSTGRES_STATEMENTS = (
    """CREATE OR REPLACE FUNCTION phm_guard_subscription_history()
    RETURNS trigger
    LANGUAGE plpgsql
    AS $phm$
    BEGIN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Subscription history is immutable.';
        END IF;
        IF NEW.customer_id IS DISTINCT FROM OLD.customer_id
           OR NEW.order_item_id IS DISTINCT FROM OLD.order_item_id
           OR NEW.plan_id IS DISTINCT FROM OLD.plan_id
           OR NEW.currency IS DISTINCT FROM OLD.currency
           OR NEW.price_cents IS DISTINCT FROM OLD.price_cents
           OR NEW.billing_interval_unit IS DISTINCT FROM OLD.billing_interval_unit
           OR NEW.billing_interval_count IS DISTINCT FROM OLD.billing_interval_count
           OR NEW.created_at IS DISTINCT FROM OLD.created_at
           OR (OLD.cancelled_at IS NOT NULL AND NEW.cancelled_at IS DISTINCT FROM OLD.cancelled_at) THEN
            RAISE EXCEPTION 'Subscription ownership and billing terms are immutable.';
        END IF;
        IF NEW.status IS DISTINCT FROM OLD.status
           AND NOT (
               (OLD.status = 'active' AND NEW.status IN ('past_due', 'suspended', 'cancelled', 'expired'))
               OR (OLD.status = 'past_due' AND NEW.status IN ('active', 'suspended', 'cancelled', 'expired'))
               OR (OLD.status = 'suspended' AND NEW.status IN ('active', 'cancelled', 'expired'))
           ) THEN
            RAISE EXCEPTION 'Invalid subscription state transition.';
        END IF;
        RETURN NEW;
    END;
    $phm$""",
    """CREATE TRIGGER subscriptions_guard_history
    BEFORE UPDATE OR DELETE ON subscriptions
    FOR EACH ROW EXECUTE FUNCTION phm_guard_subscription_history()""",
)


def install_triggers(apps, schema_editor):
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
                "PHM subscription integrity triggers support SQLite and PostgreSQL only."
            )


def remove_triggers(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute("DROP TRIGGER IF EXISTS subscriptions_reject_delete")
            cursor.execute("DROP TRIGGER IF EXISTS subscriptions_reject_terms_update")
            cursor.execute("DROP TRIGGER IF EXISTS subscriptions_reject_invalid_transition")
        elif vendor == "postgresql":
            cursor.execute(
                "DROP TRIGGER IF EXISTS subscriptions_guard_history ON subscriptions"
            )
            cursor.execute(
                "DROP FUNCTION IF EXISTS phm_guard_subscription_history()"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("subscriptions", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(install_triggers, reverse_code=remove_triggers),
    ]
