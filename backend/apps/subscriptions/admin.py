from django.contrib import admin

from .models import Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer",
        "plan",
        "status",
        "price_cents",
        "billing_interval_unit",
        "next_billing_at",
        "auto_renew",
    )
    list_filter = ("status", "auto_renew", "cancel_at_period_end", "billing_interval_unit")
    search_fields = ("=id", "customer__user__username", "customer__user__email", "plan__name")
    list_select_related = ("customer__user", "plan", "order_item")
    readonly_fields = tuple(field.name for field in Subscription._meta.fields)
    date_hierarchy = "next_billing_at"
    ordering = ("next_billing_at",)
    list_per_page = 50

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
