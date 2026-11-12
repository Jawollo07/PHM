from django.contrib import admin

from .models import Order, OrderItem


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    readonly_fields = tuple(field.name for field in OrderItem._meta.fields)
    fields = readonly_fields


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "customer",
        "status",
        "total_cents",
        "currency",
        "created_at",
        "paid_at",
    )
    list_filter = ("status", "currency", "created_at")
    search_fields = (
        "=id",
        "customer__user__username",
        "customer__user__email",
        "idempotency_key",
    )
    list_select_related = ("customer__user", "wallet_hold", "paid_transaction")
    readonly_fields = tuple(field.name for field in Order._meta.fields)
    inlines = (OrderItemInline,)
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 50

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("order", "product_name", "plan_name", "quantity", "line_total_cents")
    search_fields = ("=order__id", "product_name", "plan_name")
    list_select_related = ("order", "plan")
    readonly_fields = tuple(field.name for field in OrderItem._meta.fields)

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
