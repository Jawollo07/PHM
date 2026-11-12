from django.db import transaction
from django.utils import timezone

from apps.auth.models import UserProfile
from apps.orders.models import Order
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
        if type(remote_id) is not int or remote_id < 1 or not isinstance(remote_email, str) or remote_email.casefold() != user.email.casefold():
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
    user = order.customer.user
    try:
        account = PelicanAccount.objects.get(customer=order.customer, status=PelicanAccount.Status.LINKED)
    except PelicanAccount.DoesNotExist:
        raise PelicanAPIError("pelican_account_not_linked") from None

    config = item.resource_limits
    if not isinstance(config, dict):
        raise PelicanAPIError("invalid_plan_resources")
    config = config.get("pelican")
    if not isinstance(config, dict):
        raise PelicanAPIError("pelican_config_missing")

    required_positive = ("egg_id", "allocation_id")
    for key in required_positive:
        if type(config.get(key)) is not int or config[key] < 1:
            raise PelicanAPIError(f"invalid_{key}")
    limits = config.get("limits")
    feature_limits = config.get("feature_limits")
    environment = config.get("environment", {})
    if not isinstance(limits, dict) or not isinstance(feature_limits, dict) or not isinstance(environment, dict):
        raise PelicanAPIError("invalid_plan_resources")
    required_limits = ("memory", "swap", "disk", "io", "cpu")
    required_features = ("databases", "allocations", "backups")
    if any(type(limits.get(key)) is not int for key in required_limits):
        raise PelicanAPIError("invalid_resource_limits")
    if any(type(feature_limits.get(key)) is not int for key in required_features):
        raise PelicanAPIError("invalid_feature_limits")
    if limits["memory"] < 0 or limits["disk"] < 0 or limits["swap"] < -1 or not 10 <= limits["io"] <= 1000 or limits["cpu"] < 0:
        raise PelicanAPIError("invalid_resource_limits")
    if any(feature_limits[key] < 0 for key in required_features):
        raise PelicanAPIError("invalid_feature_limits")
    if any(not isinstance(key, str) or not key or not isinstance(value, (str, int, float, bool))
           for key, value in environment.items()):
        raise PelicanAPIError("invalid_environment")

    docker_image = config.get("docker_image")
    startup = config.get("startup")
    if not isinstance(docker_image, str) or not docker_image.strip() or not isinstance(startup, str) or not startup.strip():
        raise PelicanAPIError("invalid_egg_configuration")

    label = f"{item.product_name} {item.plan_name}".strip()[:180]
    return {
        "external_id": record.external_id,
        "name": f"{label} ({str(order.pk)[:8]})"[:255],
        "user": account.panel_user_id,
        "egg": config["egg_id"],
        "docker_image": docker_image,
        "startup": startup,
        "environment": environment,
        "limits": {key: limits[key] for key in required_limits},
        "feature_limits": {key: feature_limits[key] for key in required_features},
        "allocation": {"default": config["allocation_id"]},
    }


def _apply_remote_state(record, remote):
    remote_id, external_id = _panel_attributes(remote)
    if external_id != record.external_id:
        raise PelicanAPIError("server_identity_mismatch")
    installed_at = remote.get("installed_at")
    record.panel_server_id = remote_id
    record.panel_uuid = str(remote.get("uuid") or "")[:64]
    record.panel_identifier = str(remote.get("identifier") or "")[:32]
    record.panel_name = str(remote.get("name") or "")[:255]
    record.provisioned_at = record.provisioned_at or timezone.now()
    record.last_error_code = ""
    if installed_at:
        record.status = PelicanServer.Status.INSTALLED
        record.installed_at = record.installed_at or timezone.now()
    else:
        record.status = PelicanServer.Status.INSTALLING
    record.save(update_fields=[
        "panel_server_id", "panel_uuid", "panel_identifier", "panel_name",
        "provisioned_at", "installed_at", "status", "last_error_code", "updated_at",
    ])
    order = record.order_item.order
    if order.status == Order.Status.PAID:
        order.status = Order.Status.PROVISIONING
        order.save(update_fields=["status", "updated_at"])
    if record.status == PelicanServer.Status.INSTALLED and order.status == Order.Status.PROVISIONING:
        order.status = Order.Status.ACTIVE
        order.save(update_fields=["status", "updated_at"])
    return record


def sync_pelican_server(server_record_id, *, client=None):
    """Create or reconcile one Pelican server using a stable external_id."""
    client = client or PelicanClient()
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
        if record.order_item.order.status not in (Order.Status.PAID, Order.Status.PROVISIONING, Order.Status.ACTIVE):
            raise PelicanAPIError("order_not_paid")
        record.status = PelicanServer.Status.PROVISIONING
        record.save(update_fields=["status", "updated_at"])
        try:
            remote = client.find_server_by_external_id(record.external_id)
            if remote is None:
                payload = _server_payload(record)
                remote = client.create_server(payload)
            else:
                _remote_id, external_id = _panel_attributes(remote)
                if external_id != record.external_id:
                    raise PelicanAPIError("server_identity_mismatch")
            if record.panel_server_id and record.panel_server_id != remote.get("id"):
                raise PelicanAPIError("server_link_conflict")
            if record.panel_server_id:
                remote = client.get_server(record.panel_server_id)
            return _apply_remote_state(record, remote)
        except PelicanAPIError as exc:
            record.status = PelicanServer.Status.FAILED
            record.last_error_code = exc.code[:64]
            record.save(update_fields=["status", "last_error_code", "updated_at"])
            return record


@transaction.atomic
def enqueue_order_provisioning(order_id):
    """Create durable provisioning jobs for every paid order item."""
    order = Order.objects.select_for_update().prefetch_related("items").get(pk=order_id)
    if order.status not in (Order.Status.PAID, Order.Status.PROVISIONING, Order.Status.ACTIVE):
        return []
    records = []
    for item in order.items.all():
        record, _ = PelicanServer.objects.get_or_create(
            order_item=item,
            defaults={
                "customer": order.customer,
                "external_id": f"phm-orderitem-{item.pk}",
            },
        )
        records.append(record)
    return records
