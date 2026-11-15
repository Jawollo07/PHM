from decimal import Decimal

from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, reverse
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
    change_form_template = "admin/catalog/hostingplan/change_form.html"

    class Media:
        js = ("catalog/pelican_catalog.js",)

    def get_urls(self):
        custom = [
            path(
                "pelican-catalog/data/",
                self.admin_site.admin_view(self.pelican_catalog_data),
                name="catalog_hostingplan_pelican_catalog_data",
            )
        ]
        return custom + super().get_urls()

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["pelican_catalog_data_url"] = reverse(
            "admin:catalog_hostingplan_pelican_catalog_data"
        )
        return super().changeform_view(request, object_id, form_url, extra_context)

    def pelican_catalog_data(self, request):
        from apps.pelican.client import PelicanAPIError, PelicanClient

        try:
            client = PelicanClient()
            if request.GET.get("node_id"):
                rows = client.list_allocations(request.GET["node_id"])
                return JsonResponse({"allocations": [
                    {
                        "id": row.get("id"),
                        "ip": row.get("ip"),
                        "ip_alias": row.get("ip_alias"),
                        "port": row.get("port"),
                        "notes": row.get("notes") or "",
                    }
                    for row in rows
                    if type(row.get("id")) is int and type(row.get("port")) is int
                    and isinstance(row.get("ip"), str)
                ]})
            if request.GET.get("nest_id"):
                rows = client.list_eggs(request.GET["nest_id"])
                eggs = []
                for row in rows:
                    variables = row.get("relationships", {}).get("variables", {}).get("data", [])
                    eggs.append({
                        "id": row.get("id"),
                        "name": row.get("name"),
                        "docker_image": row.get("docker_image") or "",
                        "startup": row.get("startup") or "",
                        "variables": [
                            {
                                "env_variable": item.get("attributes", {}).get("env_variable"),
                                "default_value": item.get("attributes", {}).get("default_value"),
                            }
                            for item in variables
                            if isinstance(item, dict) and isinstance(item.get("attributes"), dict)
                            and isinstance(item["attributes"].get("env_variable"), str)
                        ],
                    })
                return JsonResponse({"eggs": eggs})
            return JsonResponse({
                "nodes": [
                    {"id": row.get("id"), "name": row.get("name")}
                    for row in client.list_nodes()
                    if type(row.get("id")) is int and isinstance(row.get("name"), str)
                ],
                "nests": [
                    {"id": row.get("id"), "name": row.get("name")}
                    for row in client.list_nests()
                    if type(row.get("id")) is int and isinstance(row.get("name"), str)
                ],
            })
        except PelicanAPIError as exc:
            return JsonResponse({"error": f"Pelican API: {exc.code}"}, status=502)

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
