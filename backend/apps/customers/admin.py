from decimal import Decimal

from django.contrib import admin

from .models import Customer, CustomerAddress, CustomerSettings


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "status",
        "phone_number",
        "wallet_balance",
        "created_at",
    )
    list_filter = ("status",)
    search_fields = ("user__username", "user__email", "id")
    readonly_fields = ("id", "user", "created_at", "updated_at")
    list_select_related = ("user", "wallet")

    @admin.display(description="Guthaben", ordering="wallet__balance_cents")
    def wallet_balance(self, obj):
        cents = obj.wallet.balance_cents
        amount = Decimal(cents) / Decimal("100")
        return f"{amount:,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CustomerAddress)
class CustomerAddressAdmin(admin.ModelAdmin):
    list_display = (
        "recipient_name",
        "customer",
        "address_type",
        "city",
        "country",
        "is_default",
    )
    list_filter = ("address_type", "country", "is_default")
    search_fields = (
        "recipient_name",
        "customer__user__username",
        "customer__user__email",
        "city",
    )


@admin.register(CustomerSettings)
class CustomerSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "customer",
        "email_notifications",
        "service_notifications",
        "payment_notifications",
        "security_notifications",
        "marketing_emails",
    )
    search_fields = ("customer__user__username", "customer__user__email")
