from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.pelican.client import PelicanAPIError, PelicanClient


class PelicanCatalogClientTests(SimpleTestCase):
    @override_settings(
        PELICAN_PANEL_URL="https://panel.example.com",
        PELICAN_APPLICATION_API_TOKEN="test-token",
    )
    def test_catalog_collection_follows_all_pages(self):
        client = PelicanClient()
        first = {
            "data": [{"attributes": {"id": 1, "name": "Node 1"}}],
            "meta": {"pagination": {"total_pages": 2}},
        }
        second = {
            "data": [{"attributes": {"id": 2, "name": "Node 2"}}],
            "meta": {"pagination": {"total_pages": 2}},
        }
        with patch.object(client, "_request", side_effect=[first, second]) as request:
            rows = client.list_nodes()
        self.assertEqual([row["id"] for row in rows], [1, 2])
        self.assertEqual(request.call_count, 2)
        self.assertIn("page=1", request.call_args_list[0].args[1])
        self.assertIn("page=2", request.call_args_list[1].args[1])

    @override_settings(
        PELICAN_PANEL_URL="https://panel.example.com",
        PELICAN_APPLICATION_API_TOKEN="test-token",
    )
    def test_eggs_include_variables_and_allocations_exclude_assigned(self):
        client = PelicanClient()
        with patch.object(client, "_request", return_value={
            "data": [{"attributes": {"id": 4, "name": "Egg"}}]
        }) as request:
            self.assertEqual(client.list_eggs(3)[0]["id"], 4)
        self.assertIn("nests/3/eggs?include=variables", request.call_args.args[1])
        with patch.object(client, "_request", return_value={
            "data": [
                {"attributes": {"id": 10, "assigned": False}},
                {"attributes": {"id": 11, "assigned": True}},
            ]
        }):
            self.assertEqual([row["id"] for row in client.list_allocations(7)], [10])

    @override_settings(
        PELICAN_PANEL_URL="https://panel.example.com",
        PELICAN_APPLICATION_API_TOKEN="test-token",
    )
    def test_invalid_node_and_nest_ids_are_rejected(self):
        client = PelicanClient()
        for method in (client.list_eggs, client.list_allocations):
            with self.subTest(method=method.__name__):
                with self.assertRaises(PelicanAPIError):
                    method(True)


class PelicanCatalogAdminTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_superuser(
            username="catalog-admin",
            email="catalog-admin@example.com",
            password="secure-test-password",
        )
        self.client.force_login(self.admin_user)

    def test_plan_form_exposes_panel_catalog_helper(self):
        response = self.client.get(reverse("admin:catalog_hostingplan_add"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Panel-Katalog laden")
        self.assertContains(response, "pelican_catalog_data_url")

    @override_settings(
        PELICAN_PANEL_URL="https://panel.example.com",
        PELICAN_APPLICATION_API_TOKEN="test-token",
    )
    @patch("apps.pelican.client.PelicanClient")
    def test_catalog_endpoint_returns_only_safe_selection_fields(self, client_class):
        client_class.return_value.list_nodes.return_value = [
            {"id": 1, "name": "Node A", "daemon_token": "must-not-leak"}
        ]
        client_class.return_value.list_nests.return_value = [
            {"id": 2, "name": "Minecraft", "secret": "must-not-leak"}
        ]
        response = self.client.get(reverse("admin:catalog_hostingplan_pelican_catalog_data"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "nodes": [{"id": 1, "name": "Node A"}],
            "nests": [{"id": 2, "name": "Minecraft"}],
        })

    def test_catalog_endpoint_requires_staff_access(self):
        self.admin_user.is_staff = False
        self.admin_user.save(update_fields=["is_staff"])
        response = self.client.get(reverse("admin:catalog_hostingplan_pelican_catalog_data"))
        self.assertEqual(response.status_code, 302)
