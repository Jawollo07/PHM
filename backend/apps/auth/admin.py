from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import EmailVerification, User, UserProfile


@admin.register(User)
class PHMUserAdmin(UserAdmin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        from apps.customers.services import provision_personal_customer
        provision_personal_customer(obj)

    list_display = ("username", "email", "email_verified", "is_active", "is_staff")
    list_filter = ("email_verified", "is_active", "is_staff", "is_superuser")
    search_fields = ("username", "email")
    ordering = ("username",)
    fieldsets = UserAdmin.fieldsets + (
        ("PHM", {"fields": ("email_verified", "email_verified_at", "created_at", "updated_at")}),
    )
    readonly_fields = ("created_at", "updated_at", "last_login", "date_joined")


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "display_name", "language", "timezone")
    search_fields = ("user__username", "user__email", "display_name")


@admin.register(EmailVerification)
class EmailVerificationAdmin(admin.ModelAdmin):
    list_display = ("user", "email", "purpose", "created_at", "expires_at", "verified_at")
    list_filter = ("purpose", "verified_at")
    search_fields = ("user__username", "email", "token_hash")
    readonly_fields = tuple(field.name for field in EmailVerification._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
