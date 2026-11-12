from django.db import transaction
from django.utils import timezone

from apps.auth.models import UserProfile
from .client import PelicanAPIError, PelicanClient
from .models import PelicanAccount


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
        first_name = display_name or user.username
        remote, _created = client.ensure_user(
            email=user.email,
            username=f"{user.username[:140]}-{account.customer_id.hex[:8]}",
            first_name=first_name,
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
