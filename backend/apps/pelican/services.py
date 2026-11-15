from datetime import timedelta

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.auth.models import UserProfile
from apps.orders.models import Order
from .configuration import PelicanConfigurationError, validate_pelican_configuration
from .client import PelicanAPIError, PelicanClient
from .models import PelicanAccount, PelicanServer


class PelicanProvisioningError(Exception):
    pass


def _panel_attributes(remote):
    if not isinstance(remote, dict):
        raise PelicanAPIError("invalid_server_response")
    remote_id = remote.get("id")
    external_id = remote.get("external_id")
    if type(remote_id) is not int or remote_id < 1:
        raise PelicanAPIError("invalid_server_response")
    return remote_id, external_id


@transaction.atomic
def sync_pelican_account(account_id, *, client=None):
    account = (PelicanAccount.objects.select_for_update()
               .select_related("customer__user").get(pk=account_id))
    user = account.customer.user
    if not user.email_verified:
        return account
    if account.status == PelicanAccount.Status.LINKED:
        return account

    account.attempts += 1
    account.last_attempt_at = timezone.now()
    account.last_error_code = ""
    account.save(update_fields=["attempts", "last_attempt_at", "last_error_code", "updated_at"])

    try:
        client = client or PelicanClient()
        profile = UserProfile.objects.filter(user=user).first()
        display_name = (profile.display_name if profile else "").strip()
        remote, _created = client.ensure_user(
            email=user.email,
            username=f"{user.username[:140]}-{account.customer_id.hex[:8]}",
            first_name=display_name or user.username,
        )
        if not isinstance(remote, dict):
            raise PelicanAPIError("invalid_user_response")
        remote_email = remote.get("email", "")
        remote_id = remote.get("id")
        if (type(remote_id) is not int or remote_id < 1
                or not isinstance(remote_email, str)
                or remote_email.casefold() != user.email.casefold()):
            raise PelicanAPIError("panel_identity_mismatch")
    except PelicanAPIError as exc:
        account.status = PelicanAccount.Status.FAILED
        account.last_error_code = exc.code[:64]
        account.save(update_fields=["status", "last_error_code", "updated_at"])
        return account

    account.panel_user_id = int(remote_id)
    account.panel_email = remote_email
    account.status = PelicanAccount.Status.LINKED
    account.linked_at = timezone.now()
    account.last_error_code = ""
    account.save(update_fields=[
        "panel_user_id", "panel_email", "status", "linked_at", "last_error_code", "updated_at"
    ])
    return account


@transaction.atomic
def sync_pelican_password(user, raw_password, *, client=None):
    """Update Pelican first; caller may save the PHM password only on success."""
    account = (PelicanAccount.objects.select_for_update()
               .filter(customer__user=user).first())
    if account is None or account.status != PelicanAccount.Status.LINKED:
        raise PelicanAPIError("pelican_account_not_linked")
    if not user.email_verified:
        raise PelicanAPIError("email_not_verified")
    client = client or PelicanClient()
    client.update_user_password(account.panel_user_id, raw_password)


def _server_payload(record):
    item = record.order_item
    order = item.order
    try:
        account = PelicanAccount.objects.get(
            customer=order.customer, status=PelicanAccount.Status.LINKED
        )
    except PelicanAccount.DoesNotExist:
        raise PelicanAPIError("pelican_account_not_linked") from None

    try:
        config = validate_pelican_configuration(item.resource_limits)
    except PelicanConfigurationError as exc:
        raise PelicanAPIError(exc.code) from None

    limits = config["limits"]
    feature_limits = config["feature_limits"]
    environment = config.get("environment", {})
    required_limits = ("memory", "swap", "disk", "io", "cpu")
    required_features = ("databases", "allocations", "backups")

    label = f"{item.product_name} {item.plan_name}".strip()[:150]
    unit_label = f" #{record.quantity_index}" if item.quantity > 1 else ""
    return {
        "external_id": record.external_id,
        "name": f"{label}{unit_label} ({str(order.pk)[:8]})"[:255],
        "user": account.panel_user_id,
        "egg": config["egg_id"],
        "docker_image": docker_image,
        "startup": startup,
        "environment": environment,
        "limits": {
            **{key: limits[key] for key in required_limits},
            **({"threads": limits["threads"]} if isinstance(limits.get("threads"), str) else {}),
        },
        "feature_limits": {key: feature_limits[key] for key in required_features},
        "allocation": {"default": config["allocation_id"]},
        "skip_scripts": config.get("skip_scripts", False),
        "oom_disabled": config.get("oom_disabled", False),
        "start_on_completion": config.get("start_on_completion", True),
    }


def _apply_remote_state(record, remote):
    remote_id, external_id = _panel_attributes(remote)
    if external_id != record.external_id:
        raise PelicanAPIError("server_identity_mismatch")
    try:
        account = PelicanAccount.objects.get(
            customer=record.customer, status=PelicanAccount.Status.LINKED
        )
    except PelicanAccount.DoesNotExist:
        raise PelicanAPIError("pelican_account_not_linked") from None
    if type(remote.get("user")) is not int or remote["user"] != account.panel_user_id:
        raise PelicanAPIError("server_owner_mismatch")

    container = remote.get("container")
    installed_at = remote.get("installed_at")
    container_installed = container.get("installed") if isinstance(container, dict) else False
    record.panel_server_id = remote_id
    record.panel_uuid = str(remote.get("uuid") or "")[:64]
    record.panel_identifier = str(remote.get("identifier") or "")[:32]
    record.panel_name = str(remote.get("name") or "")[:255]
    record.provisioned_at = record.provisioned_at or timezone.now()
    record.last_error_code = ""
    record.next_retry_at = None
    if installed_at or container_installed:
        record.status = PelicanServer.Status.INSTALLED
        record.installed_at = record.installed_at or timezone.now()
    else:
        record.status = PelicanServer.Status.INSTALLING
    record.save(update_fields=[
        "panel_server_id", "panel_uuid", "panel_identifier", "panel_name",
        "provisioned_at", "installed_at", "status", "last_error_code", "next_retry_at", "updated_at",
    ])

    order = record.order_item.order
    if order.status == Order.Status.PAID:
        order.status = Order.Status.PROVISIONING
        order.save(update_fields=["status", "updated_at"])
    if order.status == Order.Status.PROVISIONING:
        expected_units = order.items.aggregate(total=Sum("quantity"))["total"] or 0
        installed_units = PelicanServer.objects.filter(
            order_item__order=order,
            status=PelicanServer.Status.INSTALLED,
        ).count()
        if expected_units and installed_units == expected_units:
            order.status = Order.Status.ACTIVE
            order.save(update_fields=["status", "updated_at"])
    return record


def sync_pelican_server(server_record_id, *, client=None):
    """Create or reconcile one Pelican server using a stable per-unit external_id."""
    with transaction.atomic():
        record = (PelicanServer.objects.select_for_update()
                  .select_related("order_item__order__customer__user")
                  .get(pk=server_record_id))
        if record.status == PelicanServer.Status.INSTALLED:
            return record
        record.attempts += 1
        record.last_attempt_at = timezone.now()
        record.last_error_code = ""
        record.save(update_fields=["attempts", "last_attempt_at", "last_error_code", "updated_at"])
        if record.order_item.order.status not in (
            Order.Status.PAID, Order.Status.PROVISIONING, Order.Status.ACTIVE
        ):
            raise PelicanAPIError("order_not_paid")
        record.status = PelicanServer.Status.PROVISIONING
        record.save(update_fields=["status", "updated_at"])
        try:
            client = client or PelicanClient()
            remote = client.find_server_by_external_id(record.external_id)
            if remote is None:
                remote = client.create_server(_server_payload(record))
            else:
                _remote_id, external_id = _panel_attributes(remote)
                if external_id != record.external_id:
                    raise PelicanAPIError("server_identity_mismatch")
            remote_id, _external_id = _panel_attributes(remote)
            if record.panel_server_id and record.panel_server_id != remote_id:
                raise PelicanAPIError("server_link_conflict")
            remote = client.get_server(remote_id)
            return _apply_remote_state(record, remote)
        except PelicanAPIError as exc:
            record.status = PelicanServer.Status.FAILED
            record.last_error_code = exc.code[:64]
            retry_seconds = min(60 * (2 ** min(max(record.attempts - 1, 0), 8)), 21600)
            record.next_retry_at = timezone.now() + timedelta(seconds=retry_seconds)
            record.save(update_fields=["status", "last_error_code", "next_retry_at", "updated_at"])
            return record


@transaction.atomic
def enqueue_order_provisioning(order_id):
    """Create one idempotent durable job for every purchased server unit."""
    order = Order.objects.select_for_update().prefetch_related("items").get(pk=order_id)
    if order.status not in (Order.Status.PAID, Order.Status.PROVISIONING, Order.Status.ACTIVE):
        return []
    records = []
    for item in order.items.all():
        for unit_index in range(1, item.quantity + 1):
            external_id = (
                f"phm-orderitem-{item.pk}" if unit_index == 1
                else f"phm-orderitem-{item.pk}-unit-{unit_index}"
            )
            record, _ = PelicanServer.objects.get_or_create(
                order_item=item,
                quantity_index=unit_index,
                defaults={"customer": order.customer, "external_id": external_id},
            )
            if record.customer_id != order.customer_id or record.external_id != external_id:
                raise PelicanAPIError("provisioning_record_identity_conflict")
            records.append(record)
    return records



def _server_should_be_suspended(record, *, now=None):
    """Derive access from PHM's order and recurring-subscription source of truth."""
    now = now or timezone.now()
    order = record.order_item.order
    if order.status != Order.Status.ACTIVE:
        return True

    subscription = getattr(record.order_item, "subscription", None)
    if subscription is None:
        # One-time purchases remain active for the lifetime of the order.
        return False

    if subscription.current_period_end <= now:
        return True
    return subscription.status != "active"


def sync_pelican_server_access(server_record_id, *, client=None, now=None):
    """Idempotently align Pelican suspension with PHM billing state."""
    now = now or timezone.now()
    with transaction.atomic():
        record = (PelicanServer.objects.select_for_update()
                  .select_related("order_item__order", "order_item__subscription", "customer")
                  .get(pk=server_record_id))
        if record.status != PelicanServer.Status.INSTALLED or not record.panel_server_id:
            return record, True

        record.attempts += 1
        record.last_attempt_at = now
        record.last_error_code = ""
        record.save(update_fields=["attempts", "last_attempt_at", "last_error_code", "updated_at"])

        should_suspend = _server_should_be_suspended(record, now=now)
        try:
            client = client or PelicanClient()
            remote = client.get_server(record.panel_server_id)
            remote_id, external_id = _panel_attributes(remote)
            if remote_id != record.panel_server_id or external_id != record.external_id:
                raise PelicanAPIError("server_identity_mismatch")

            account = PelicanAccount.objects.get(
                customer=record.customer, status=PelicanAccount.Status.LINKED
            )
            if type(remote.get("user")) is not int or remote["user"] != account.panel_user_id:
                raise PelicanAPIError("server_owner_mismatch")

            remote_status = remote.get("status")
            if remote_status is not None and not isinstance(remote_status, str):
                raise PelicanAPIError("invalid_server_response")
            remotely_suspended = remote_status == "suspended"

            if should_suspend and not remotely_suspended:
                client.suspend_server(record.panel_server_id)
            elif not should_suspend and remotely_suspended:
                client.unsuspend_server(record.panel_server_id)

            record.last_error_code = ""
            record.next_retry_at = None
            record.save(update_fields=["last_error_code", "next_retry_at", "updated_at"])
        except (PelicanAPIError, PelicanAccount.DoesNotExist) as exc:
            code = exc.code if isinstance(exc, PelicanAPIError) else "pelican_account_not_linked"
            record.last_error_code = code[:64]
            retry_seconds = min(60 * (2 ** min(max(record.attempts - 1, 0), 8)), 21600)
            record.next_retry_at = now + timedelta(seconds=retry_seconds)
            record.save(update_fields=["last_error_code", "next_retry_at", "updated_at"])

        return record, should_suspend
