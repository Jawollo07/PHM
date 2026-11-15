from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q


class HostingProduct(models.Model):
    """A sellable hosting product, independent of any customer or company tenant."""

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "catalog_hosting_products"
        ordering = ["sort_order", "name"]
        verbose_name = "Hosting product"
        verbose_name_plural = "Hosting products"
        indexes = [
            models.Index(fields=["is_active", "sort_order"], name="catalog_product_active_idx"),
        ]

    def __str__(self):
        return self.name


class HostingPlan(models.Model):
    """A priced, configurable offer belonging to a hosting product.

    All prices are EUR cents. Resource limits remain structured data so the
    catalog does not assume a specific hosting platform or product family.
    """

    class IntervalUnit(models.TextChoices):
        ONCE = "once", "Einmalig"
        DAY = "day", "Tag(e)"
        WEEK = "week", "Woche(n)"
        MONTH = "month", "Monat(e)"
        YEAR = "year", "Jahr(e)"

    product = models.ForeignKey(
        HostingProduct,
        on_delete=models.PROTECT,
        related_name="plans",
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140)
    description = models.TextField(blank=True, default="")
    price_cents = models.BigIntegerField(validators=[MinValueValidator(0)])
    setup_fee_cents = models.BigIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
    )
    billing_interval_unit = models.CharField(
        max_length=10,
        choices=IntervalUnit.choices,
        default=IntervalUnit.MONTH,
    )
    billing_interval_count = models.PositiveSmallIntegerField(default=1)
    resource_limits = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "catalog_hosting_plans"
        ordering = ["product__sort_order", "sort_order", "name"]
        verbose_name = "Hosting plan"
        verbose_name_plural = "Hosting plans"
        constraints = [
            models.UniqueConstraint(
                fields=["product", "slug"],
                name="catalog_plan_product_slug_unique",
            ),
            models.CheckConstraint(
                condition=Q(price_cents__gte=0),
                name="catalog_plan_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(setup_fee_cents__gte=0),
                name="catalog_plan_setup_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(billing_interval_count__gte=1),
                name="catalog_plan_interval_positive",
            ),
            models.CheckConstraint(
                condition=(
                    Q(billing_interval_unit="once", billing_interval_count=1)
                    | ~Q(billing_interval_unit="once")
                ),
                name="catalog_plan_once_interval_one",
            ),
            models.CheckConstraint(
                condition=Q(billing_interval_unit__in=[
                    "once", "day", "week", "month", "year"
                ]),
                name="catalog_plan_interval_unit_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["product", "is_active", "sort_order"],
                name="catalog_plan_active_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if not isinstance(self.resource_limits, dict):
            raise ValidationError({
                "resource_limits": "Ressourcenlimits müssen als JSON-Objekt gespeichert werden."
            })
        if self.billing_interval_unit == self.IntervalUnit.ONCE and self.billing_interval_count != 1:
            raise ValidationError({
                "billing_interval_count": "Einmalige Angebote haben genau ein Intervall."
            })
        if "pelican" in self.resource_limits:
            from apps.pelican.configuration import (
                PelicanConfigurationError,
                validate_pelican_configuration,
            )

            try:
                validate_pelican_configuration(self.resource_limits)
            except PelicanConfigurationError as exc:
                messages = {
                    "invalid_egg_id": "Die Pelican-Egg-ID muss eine positive Ganzzahl sein.",
                    "invalid_allocation_id": "Die Pelican-Allocation-ID muss eine positive Ganzzahl sein.",
                    "invalid_plan_resources": "Pelican limits, feature_limits und environment müssen JSON-Objekte sein.",
                    "invalid_resource_limits": "Die Pelican-Ressourcenlimits sind ungültig.",
                    "invalid_feature_limits": "Die Pelican Feature-Limits sind ungültig.",
                    "invalid_environment": "Die Pelican-Environment-Werte müssen einfache JSON-Werte sein.",
                    "invalid_egg_configuration": "Docker-Image und Startup müssen gesetzt sein; Optionen müssen boolesch sein.",
                }
                raise ValidationError({
                    "resource_limits": messages.get(
                        exc.code, "Die Pelican-Konfiguration ist ungültig."
                    )
                }) from None

    def __str__(self):
        return f"{self.product.name} – {self.name}"

    @property
    def price_eur(self):
        return Decimal(self.price_cents) / Decimal("100")

    @property
    def setup_fee_eur(self):
        return Decimal(self.setup_fee_cents) / Decimal("100")
