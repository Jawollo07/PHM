from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.auth.models import User
from apps.customers.models import Customer
from .models import PelicanAccount


@receiver(post_save, sender=User, dispatch_uid="pelican.enqueue_verified_customer")
def enqueue_verified_customer(sender, instance, update_fields=None, **kwargs):
    if not instance.email_verified:
        return
    if update_fields is not None and not {"email_verified", "email"}.intersection(update_fields):
        return
    customer = Customer.objects.filter(user=instance).first()
    if customer is not None:
        PelicanAccount.objects.get_or_create(customer=customer)
