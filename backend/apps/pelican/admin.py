from django.contrib import admin

from .models import PelicanAccount


@admin.register(PelicanAccount)
class PelicanAccountAdmin(admin.ModelAdmin):
    list_display = ("customer", "panel_user_id", "panel_email", "status", "attempts", "last_attempt_at", "linked_at")
    list_filter = ("status",)
    search_fields = ("customer__user__username", "customer__user__email", "panel_email", "panel_user_id")
    readonly_fields = (
        "id", "customer", "panel_user_id", "panel_email", "status",
        "last_error_code", "attempts", "last_attempt_at", "linked_at",
        "created_at", "updated_at",
    )
    list_select_related = ("customer__user",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD") and super().has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return False
