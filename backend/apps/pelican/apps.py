from django.apps import AppConfig


class PelicanConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.pelican"
    label = "pelican"
    verbose_name = "Pelican Panel integration"

    def ready(self):
        from . import signals  # noqa: F401
