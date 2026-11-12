from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from apps.catalog.models import HostingPlan, HostingProduct


class HostingCatalogModelTests(TestCase):
    def setUp(self):
        self.product = HostingProduct.objects.create(
            name="Game Server",
            slug="game-server",
            description="Private game server hosting",
            is_active=True,
        )

    def test_plan_stores_eur_cents_and_configurable_billing_interval(self):
        plan = HostingPlan.objects.create(
            product=self.product,
            name="Starter",
            slug="starter",
            price_cents=1299,
            setup_fee_cents=250,
            billing_interval_unit=HostingPlan.IntervalUnit.MONTH,
            billing_interval_count=3,
            resource_limits={"memory_mb": 4096, "disk_gb": 30},
            is_active=True,
        )
        self.assertEqual(plan.price_cents, 1299)
        self.assertEqual(plan.setup_fee_cents, 250)
        self.assertEqual(plan.price_eur, 12.99)
        self.assertEqual(plan.billing_interval_count, 3)

    def test_free_plan_is_valid_and_does_not_use_negative_money(self):
        plan = HostingPlan.objects.create(
            product=self.product,
            name="Free",
            slug="free",
            price_cents=0,
            billing_interval_unit=HostingPlan.IntervalUnit.ONCE,
        )
        self.assertEqual(plan.price_cents, 0)

    def test_once_plan_must_have_exactly_one_interval(self):
        plan = HostingPlan(
            product=self.product,
            name="Invalid",
            slug="invalid",
            price_cents=100,
            billing_interval_unit=HostingPlan.IntervalUnit.ONCE,
            billing_interval_count=2,
        )
        with self.assertRaisesMessage(Exception, "Einmalige Angebote"):
            plan.full_clean()

    def test_resource_limits_must_be_a_json_object(self):
        plan = HostingPlan(
            product=self.product,
            name="Invalid limits",
            slug="invalid-limits",
            price_cents=100,
            resource_limits=["not", "an", "object"],
        )
        with self.assertRaisesMessage(Exception, "JSON-Objekt"):
            plan.full_clean()

    def test_database_rejects_negative_plan_price(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            HostingPlan.objects.create(
                product=self.product,
                name="Negative",
                slug="negative",
                price_cents=-1,
            )

    def test_plan_slug_is_unique_per_product(self):
        HostingPlan.objects.create(
            product=self.product,
            name="Starter",
            slug="starter",
            price_cents=100,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            HostingPlan.objects.create(
                product=self.product,
                name="Another Starter",
                slug="starter",
                price_cents=200,
            )

    def test_same_plan_slug_can_be_used_for_another_product(self):
        second_product = HostingProduct.objects.create(
            name="VPS",
            slug="vps",
        )
        HostingPlan.objects.create(
            product=self.product,
            name="Starter",
            slug="starter",
            price_cents=100,
        )
        plan = HostingPlan.objects.create(
            product=second_product,
            name="Starter",
            slug="starter",
            price_cents=200,
        )
        self.assertEqual(plan.product, second_product)


class HostingCatalogAdminTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_superuser(
            username="catalog-admin",
            email="catalog-admin@example.com",
            password="secure-test-password",
        )
        self.client.force_login(self.admin_user)

    def test_product_and_plan_are_manageable_in_admin(self):
        product = HostingProduct.objects.create(
            name="VPS",
            slug="vps",
        )
        plan = HostingPlan.objects.create(
            product=product,
            name="Small",
            slug="small",
            price_cents=499,
        )
        product_response = self.client.get(reverse("admin:catalog_hostingproduct_changelist"))
        plan_response = self.client.get(reverse("admin:catalog_hostingplan_changelist"))
        self.assertEqual(product_response.status_code, 200)
        self.assertEqual(plan_response.status_code, 200)
        self.assertContains(plan_response, "4,99 EUR")
        self.assertContains(product_response, "VPS")
