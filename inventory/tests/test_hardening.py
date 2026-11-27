"""PD3 hardening tests: validation, error pages, access control, CSRF and data integrity."""
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from inventory.models import Category, Product, StockMovement

from .helpers import PASSWORD, make_product, make_user


class ValidInputTests(TestCase):
    """Valid input is saved and the user sees a success message."""

    def setUp(self):
        self.owner = make_user("owner@example.com", "OWNER")
        self.client.force_login(self.owner)

    def test_valid_restock_saves_and_redirects(self):
        product = make_product(self.owner)
        resp = self.client.post(reverse("inventory:movement_create"),
                                {"movement_type": "RESTOCK", "product": product.pk, "quantity": "12",
                                 "reason": "Delivery"})
        self.assertRedirects(resp, reverse("inventory:movement_list"))  # redirect after POST
        product.refresh_from_db()
        self.assertEqual(product.stock_qty, 12)
        self.assertEqual(StockMovement.objects.get().recorded_by, self.owner)


class InvalidInputTests(TestCase):
    """Server-side validation rejects bad input even when the browser's checks are skipped."""

    def setUp(self):
        self.owner = make_user("owner@example.com", "OWNER")
        self.client.force_login(self.owner)
        self.product = make_product(self.owner, stock=5)

    def post_stock(self, **data):
        base = {"movement_type": "RESTOCK", "product": self.product.pk, "quantity": "1", "reason": ""}
        base.update(data)
        return self.client.post(reverse("inventory:movement_create"), base)

    def test_rejects_bad_quantities(self):
        for qty, message in [("", "Enter how many units."), ("-3", "Enter at least 1."),
                             ("2.5", "Enter a whole number."), ("10001", "Enter 10,000 or less.")]:
            with self.subTest(qty=qty):
                resp = self.post_stock(quantity=qty)
                self.assertEqual(resp.status_code, 200)
                self.assertIn(message, str(resp.context["form"].errors["quantity"]))
        self.assertFalse(StockMovement.objects.exists())

    def test_rejects_tampered_choices(self):
        resp = self.post_stock(movement_type="SALE")
        self.assertIn("movement_type", resp.context["form"].errors)
        resp = self.post_stock(product="99999")
        self.assertIn("product", resp.context["form"].errors)
        resp = self.post_stock(movement_type="ADJUSTMENT", direction="sideways", reason="x")
        self.assertIn("direction", resp.context["form"].errors)

    def test_no_negative_stock(self):
        resp = self.post_stock(movement_type="ADJUSTMENT", direction="remove", quantity="6", reason="Expired")
        self.assertIn("at most 5", str(resp.context["form"].errors["quantity"]))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 5)

    def test_product_price_and_code_rules(self):
        resp = self.client.post(reverse("inventory:product_create"), {
            "product_code": "<b>X</b>", "name": "   ", "category": self.product.category.pk, "unit": "can",
            "cost_price": "abc", "selling_price": "-5", "reorder_level": "1.5"})
        errors = resp.context["form"].errors
        for field in ["product_code", "name", "cost_price", "selling_price", "reorder_level"]:
            self.assertIn(field, errors, field)
        self.assertContains(resp, "wasn&#x27;t added")
        self.assertEqual(Product.objects.count(), 1)

    def test_long_search_text_is_rejected_not_crashing(self):
        resp = self.client.get(reverse("inventory:product_list") + "?q=" + "a" * 500)
        self.assertEqual(resp.status_code, 200)

    def test_invalid_filters_do_not_crash(self):
        for query in ["?category=abc", "?stock=weird", "?status=deleted", "?category=99999"]:
            self.assertEqual(self.client.get(reverse("inventory:product_list") + query).status_code, 200, query)
        for query in ["?date_from=not-a-date", "?type=SALE", "?date_from=2026-13-40"]:
            self.assertEqual(self.client.get(reverse("inventory:movement_list") + query).status_code, 200, query)


class LoginRequiredTests(TestCase):
    """Every core-feature page sends logged-out users to the login page, GET or POST."""

    def test_all_inventory_pages_require_login(self):
        owner = make_user("owner@example.com", "OWNER")
        product = make_product(owner)
        movement = StockMovement.objects.create(product=product, recorded_by=owner,
                                                movement_type="RESTOCK", quantity_change=1)
        urls = [reverse("inventory:category_list"), reverse("inventory:category_create"),
                reverse("inventory:category_edit", args=[product.category.pk]),
                reverse("inventory:category_delete", args=[product.category.pk]),
                reverse("inventory:product_list"), reverse("inventory:product_create"),
                reverse("inventory:product_detail", args=[product.pk]),
                reverse("inventory:product_edit", args=[product.pk]),
                reverse("inventory:product_delete", args=[product.pk]),
                reverse("inventory:movement_list"), reverse("inventory:movement_create"),
                reverse("inventory:movement_edit", args=[movement.pk]),
                reverse("inventory:movement_delete", args=[movement.pk]),
                reverse("accounts:team")]
        for url in urls:
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), f"{reverse('accounts:login')}?next={url}")
        resp = self.client.post(reverse("inventory:movement_delete", args=[movement.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(StockMovement.objects.filter(pk=movement.pk).exists())


class OtherUsersRecordsTests(TestCase):
    """Changing the ID in the URL does not open or change someone else's record."""

    def setUp(self):
        self.owner = make_user("owner@example.com", "OWNER")
        self.joy = make_user("joy@example.com", "HELPER")
        self.ben = make_user("ben@example.com", "HELPER")
        self.product = make_product(self.owner, stock=0)
        self.client.force_login(self.ben)
        self.client.post(reverse("inventory:movement_create"),
                         {"movement_type": "RESTOCK", "product": self.product.pk, "quantity": "10"})
        self.bens = StockMovement.objects.get()
        self.client.force_login(self.joy)

    def test_cannot_view_edit_or_delete_by_changing_id(self):
        edit = reverse("inventory:movement_edit", args=[self.bens.pk])
        delete = reverse("inventory:movement_delete", args=[self.bens.pk])
        self.assertEqual(self.client.get(edit).status_code, 404)
        self.assertEqual(self.client.post(edit, {"quantity": "1", "reason": "x"}).status_code, 404)
        self.assertEqual(self.client.get(delete).status_code, 404)
        self.assertEqual(self.client.post(delete).status_code, 404)
        self.bens.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((self.bens.quantity_change, self.product.stock_qty), (10, 10))

    def test_helper_cannot_use_owner_actions_by_url(self):
        for url in [reverse("inventory:product_edit", args=[self.product.pk]),
                    reverse("inventory:product_delete", args=[self.product.pk]),
                    reverse("inventory:product_toggle_active", args=[self.product.pk]),
                    reverse("inventory:category_delete", args=[self.product.category.pk])]:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, {"selling_price": "1"}).status_code, 403)
        self.product.refresh_from_db()
        self.assertTrue(self.product.is_active)

    def test_not_found_ids_show_custom_404(self):
        for url in [reverse("inventory:product_detail", args=[99999]),
                    reverse("inventory:movement_edit", args=[99999]), "/inventory/products/abc/"]:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 404)
                self.assertContains(resp, "find that page", status_code=404)


class MethodAndCsrfTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com", "OWNER")
        self.product = make_product(self.owner)

    def test_destructive_actions_need_post(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("inventory:product_toggle_active", args=[self.product.pk])).status_code, 405)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)
        # GET on delete only shows the confirmation page; nothing is deleted.
        resp = self.client.get(reverse("inventory:product_delete", args=[self.product.pk]))
        self.assertContains(resp, "Delete the product")
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())
        self.assertEqual(self.client.post(reverse("inventory:product_list")).status_code, 405)

    def test_post_without_csrf_token_is_refused(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        resp = client.post(reverse("inventory:product_delete", args=[self.product.pk]))
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "This form expired", status_code=403)
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_every_post_form_has_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for url in [reverse("inventory:product_create"), reverse("inventory:movement_create"),
                    reverse("inventory:product_delete", args=[self.product.pk]),
                    reverse("inventory:product_detail", args=[self.product.pk]), reverse("accounts:team")]:
            html = client.get(url).content.decode()
            self.assertEqual(html.count('method="post"'), html.count("csrfmiddlewaretoken"), url)


@override_settings(ROOT_URLCONF="inventory.tests.error_urls", DEBUG=False)
class ServerErrorPageTests(TestCase):
    def test_crash_shows_custom_500_without_traceback(self):
        client = Client(raise_request_exception=False)
        resp = client.get("/boom/")
        self.assertEqual(resp.status_code, 500)
        self.assertContains(resp, "Something went wrong on our side", status_code=500)
        self.assertNotContains(resp, "Traceback", status_code=500)
        self.assertNotContains(resp, "RuntimeError", status_code=500)


class DataIntegrityTests(TestCase):
    """PostgreSQL rejects bad rows even if a bug or the admin skips the forms."""

    def setUp(self):
        self.owner = make_user("owner@example.com", "OWNER")
        self.product = make_product(self.owner)

    def assertRejected(self, func):
        with self.assertRaises(IntegrityError), transaction.atomic():
            func()

    def test_constraints(self):
        self.assertRejected(lambda: Category.objects.create(name="CANNED GOODS", created_by=self.owner))
        self.assertRejected(lambda: Product.objects.filter(pk=self.product.pk).update(product_code="lower-1"))
        self.assertRejected(lambda: StockMovement.objects.create(
            product=self.product, recorded_by=self.owner, movement_type="ADJUSTMENT", quantity_change=-1, reason=""))
        self.assertRejected(lambda: StockMovement.objects.create(
            product=self.product, recorded_by=self.owner, movement_type="RESTOCK", quantity_change=50000))

    def test_protect_keeps_history(self):
        from django.db.models import ProtectedError
        StockMovement.objects.create(product=self.product, recorded_by=self.owner,
                                     movement_type="RESTOCK", quantity_change=3)
        with self.assertRaises(ProtectedError):
            self.product.delete()
        with self.assertRaises(ProtectedError):
            self.owner.delete()

    def test_duplicate_name_race_becomes_form_error(self):
        """If the form's duplicate check is passed (e.g. two saves at once), the DB error becomes a message."""
        from unittest import mock
        self.client.force_login(self.owner)
        with mock.patch("inventory.forms.CategoryForm.clean_name", lambda form: "Canned goods"):
            resp = self.client.post(reverse("inventory:category_create"), {"name": "Canned goods"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("already exists", str(resp.context["form"].errors["name"]))
        self.assertEqual(Category.objects.count(), 1)

    def test_list_pages_query_count_does_not_grow_with_rows(self):
        """select_related keeps each list page to a fixed number of queries (no N+1)."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.client.force_login(self.owner)

        def count(url):
            with CaptureQueriesContext(connection) as ctx:
                self.client.get(url)
            return len(ctx.captured_queries)

        def add_rows(start):
            for i in range(start, start + 5):
                p = make_product(self.owner, code=f"P-{i}", name=f"Item {i}")
                StockMovement.objects.create(product=p, recorded_by=self.owner,
                                             movement_type="RESTOCK", quantity_change=2)

        add_rows(0)
        before = [count(reverse("inventory:movement_list")), count(reverse("inventory:product_list"))]
        add_rows(5)
        after = [count(reverse("inventory:movement_list")), count(reverse("inventory:product_list"))]
        self.assertEqual(before, after)


class StandardFeaturesStillWorkTests(TestCase):
    """Smoke test of the PD1 flow after hardening."""

    def test_register_login_dashboard_profile_logout(self):
        self.client.post(reverse("accounts:register"), {
            "full_name": "Nena Cruz", "email": "nena@example.com", "password1": PASSWORD, "password2": PASSWORD})
        resp = self.client.post(reverse("accounts:login"),
                                {"username": "nena@example.com", "password": PASSWORD}, follow=True)
        self.assertRedirects(resp, reverse("accounts:owner_dashboard"))
        self.assertContains(self.client.get(reverse("accounts:profile")), "nena@example.com")
        self.client.post(reverse("accounts:logout"))
        self.assertEqual(self.client.get(reverse("accounts:profile")).status_code, 302)
