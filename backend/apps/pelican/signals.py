from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.auth.models import User
from apps.customers.models import Customer
from .models import PelicanAccount


@receiver(post_save, sender=User, dispatch_uid="pelican.enqueue_verified_customer")
def enqueue_verified_customer(sender, instance, update_fields=None, **kwargs):
    if not instance.email_verified or instance.is_staff:
        return
    if update_fields is not None and not {"email_verified", "email"}.intersection(update_fields):
        return
    customer = Customer.objects.filter(user=instance).first()
    if customer is None:
        return
    account, _ = PelicanAccount.objects.get_or_create(customer=customer)
    # Provision only after the PHM verification transaction commits. API errors are
    # recorded on the link row and can be retried with sync_pelican_accounts.
    transaction.on_commit(
        lambda account_id=account.pk: _sync_after_commit(account_id)
    )


def _sync_after_commit(account_id):
    from .services import sync_pelican_account
    sync_pelican_account(account_id)
