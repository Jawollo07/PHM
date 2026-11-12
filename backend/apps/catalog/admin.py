from decimal import Decimal

from django.contrib import admin
from django.utils.html import format_html

from .models import HostingPlan, HostingProduct


def eur(cents):
    value = Decimal(cents) / Decimal("100")
    return f"{value:,.2f} EUR".replace(",", "X").replace(".", ",").replace("X", ".")


class HostingPlanInline(admin.TabularInline):
    model = HostingPlan
    extra = 0
    fields = (
        "name",
        "slug",
        "price_cents",
        "billing_interval_unit",
        "billing_interval_count",
        "is_active",
    )
    show_change_link = True


@admin.register(HostingProduct)
class HostingProductAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "plan_count", "is_active", "sort_order", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("sort_order", "name")
    inlines = (HostingPlanInline,)
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Tarife")
    def plan_count(self, obj):
        return obj.plans.count()


@admin.register(HostingPlan)
class HostingPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "product",
        "price_display",
        "billing_period",
        "setup_fee_display",
        "is_active",
        "sort_order",
    )
    list_filter = ("product", "is_active", "billing_interval_unit")
    search_fields = ("name", "slug", "product__name", "description")
    prepopulated_fields = {"slug": ("name",)}
    list_select_related = ("product",)
    ordering = ("product__sort_order", "sort_order", "name")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Angebot", {
            "fields": ("product", "name", "slug", "description", "is_active", "sort_order")
        }),
        ("Preis und Laufzeit", {
            "fields": (
                "price_cents",
                "setup_fee_cents",
                "billing_interval_unit",
                "billing_interval_count",
            )
        }),
        ("Ressourcen", {"fields": ("resource_limits",)}),
        ("Zeitstempel", {"fields": ("created_at", "updated_at")}),
    )

    @admin.display(description="Preis", ordering="price_cents")
    def price_display(self, obj):
        return eur(obj.price_cents)

    @admin.display(description="Abrechnungsintervall")
    def billing_period(self, obj):
        if obj.billing_interval_unit == HostingPlan.IntervalUnit.ONCE:
            return "Einmalig"
        unit = obj.get_billing_interval_unit_display()
        return f"{obj.billing_interval_count} {unit}"

    @admin.display(description="Einrichtungsgebühr", ordering="setup_fee_cents")
    def setup_fee_display(self, obj):
        return eur(obj.setup_fee_cents)
