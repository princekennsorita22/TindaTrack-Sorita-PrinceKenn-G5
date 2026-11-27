from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from inventory.models import Product, StockMovement

from .helpers import make_product, make_user


class StockFlowTests(TestCase):
    """End to end: owner adds a product, helper restocks it, stock and log stay in step."""

    def setUp(self):
        self.owner = make_user("owner@example.com", "OWNER")
        self.helper = make_user("helper@example.com", "HELPER")
        self.product = make_product(self.owner, stock=0, reorder=5)
        self.url = reverse("inventory:movement_create")

    def post(self, **kw):
        data = {"movement_type": "RESTOCK", "product": self.product.pk, "quantity": "24",
                "direction": "add", "reason": "Delivery"}
        data.update(kw)
        return self.client.post(self.url, data, follow=True)

    def test_logged_out_redirects(self):
        for url in [self.url, reverse("inventory:movement_list")]:
            self.assertRedirects(self.client.get(url), f"{reverse('accounts:login')}?next={url}")

    def test_helper_restock_updates_stock_and_links_user(self):
        self.client.force_login(self.helper)
        resp = self.post()
        self.assertContains(resp, "24 added to Sardinas 155g. Stock is now 24.")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 24)
        m = StockMovement.objects.get()
        self.assertEqual((m.recorded_by, m.quantity_change, m.movement_type), (self.helper, 24, "RESTOCK"))

    def test_restock_ignores_remove_direction(self):
        self.client.force_login(self.helper)
        self.post(direction="remove")
        self.assertEqual(StockMovement.objects.get().quantity_change, 24)

    def test_adjustment_removes_and_warns_when_low(self):
        self.client.force_login(self.helper)
        self.post(quantity="10")
        resp = self.post(movement_type="ADJUSTMENT", direction="remove", quantity="7", reason="Damaged cans")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 3)
        self.assertContains(resp, "is low on stock")

    def test_adjustment_cannot_go_below_zero(self):
        self.client.force_login(self.helper)
        self.post(quantity="5")
        resp = self.post(movement_type="ADJUSTMENT", direction="remove", quantity="6", reason="Expired")
        self.assertIn("at most 5", str(resp.context["form"].errors["quantity"]))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 5)

    def test_validation_messages(self):
        self.client.force_login(self.helper)
        resp = self.post(product="", quantity="0")
        errors = resp.context["form"].errors
        self.assertIn("product", errors)
        self.assertIn("Enter at least 1.", str(errors["quantity"]))
        self.assertContains(resp, "wasn&#x27;t saved")
        resp = self.post(movement_type="ADJUSTMENT", reason="")
        self.assertIn("reason", resp.context["form"].errors)
        resp = self.post(quantity="abc")
        self.assertIn("Enter a whole number.", str(resp.context["form"].errors["quantity"]))
        self.assertFalse(StockMovement.objects.exists())

    def test_cannot_restock_deactivated_product(self):
        self.product.is_active = False
        self.product.save()
        self.client.force_login(self.owner)
        resp = self.post()
        self.assertIn("product", resp.context["form"].errors)

    def test_product_with_history_cannot_be_deleted(self):
        self.client.force_login(self.owner)
        self.post()
        resp = self.client.post(reverse("inventory:product_delete", args=[self.product.pk]), follow=True)
        self.assertContains(resp, "Deactivate it instead")
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())


class StockOwnershipTests(TestCase):
    """Helpers see and change only their own entries; owners see and change all."""

    def setUp(self):
        self.owner = make_user("owner@example.com", "OWNER")
        self.helper = make_user("helper@example.com", "HELPER")
        self.other = make_user("other@example.com", "HELPER")
        self.product = make_product(self.owner)
        self.client.force_login(self.helper)
        self.client.post(reverse("inventory:movement_create"),
                         {"movement_type": "RESTOCK", "product": self.product.pk, "quantity": "20"})
        self.mine = StockMovement.objects.get()
        self.client.force_login(self.other)
        self.client.post(reverse("inventory:movement_create"),
                         {"movement_type": "RESTOCK", "product": self.product.pk, "quantity": "7",
                          "reason": "Other helper's delivery"})
        self.theirs = StockMovement.objects.exclude(pk=self.mine.pk).get()
        self.client.force_login(self.helper)

    def test_helper_list_shows_only_own(self):
        resp = self.client.get(reverse("inventory:movement_list"))
        self.assertEqual(list(resp.context["movements"]), [self.mine])
        self.assertNotContains(resp, "Other helper")

    def test_helper_cannot_open_others_entries(self):
        for name in ["movement_edit", "movement_delete"]:
            self.assertEqual(self.client.get(reverse(f"inventory:{name}", args=[self.theirs.pk])).status_code, 404)
        self.client.post(reverse("inventory:movement_delete", args=[self.theirs.pk]))
        self.assertTrue(StockMovement.objects.filter(pk=self.theirs.pk).exists())

    def test_helper_edits_own_entry_and_stock_follows(self):
        resp = self.client.post(reverse("inventory:movement_edit", args=[self.mine.pk]),
                                {"quantity": "12", "reason": "Recounted delivery"}, follow=True)
        self.assertContains(resp, "now has 19 in stock")
        self.mine.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual((self.mine.quantity_change, self.product.stock_qty), (12, 19))

    def test_owner_sees_all_and_deletes_any(self):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("inventory:movement_list"))
        self.assertEqual(len(resp.context["movements"]), 2)
        self.client.post(reverse("inventory:movement_delete", args=[self.theirs.pk]))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 20)
        self.assertFalse(StockMovement.objects.filter(pk=self.theirs.pk).exists())

    def test_delete_blocked_when_units_already_used(self):
        self.client.post(reverse("inventory:movement_create"),
                         {"movement_type": "ADJUSTMENT", "direction": "remove", "product": self.product.pk,
                          "quantity": "25", "reason": "Expired"})
        resp = self.client.post(reverse("inventory:movement_delete", args=[self.mine.pk]), follow=True)
        self.assertContains(resp, "below zero")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_qty, 2)

    def test_filters(self):
        self.client.force_login(self.owner)
        url = reverse("inventory:movement_list")
        self.assertEqual(len(self.client.get(url + "?type=ADJUSTMENT").context["movements"]), 0)
        self.assertEqual(len(self.client.get(url + "?q=sard").context["movements"]), 2)
        resp = self.client.get(url + "?date_from=2030-01-02&date_to=2030-01-01")
        self.assertContains(resp, "on or before")

    def test_dashboards_show_stock(self):
        resp = self.client.get(reverse("accounts:helper_dashboard"))
        self.assertContains(resp, "Your recent entries")
        self.assertContains(resp, "+20")
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("accounts:owner_dashboard"))
        self.assertEqual(resp.context["low_count"], 0)
        self.assertContains(resp, "Latest stock changes")


class StockConstraintTests(TestCase):
    def test_database_rejects_bad_movements(self):
        owner = make_user("owner@example.com", "OWNER")
        p = make_product(owner)
        bad = [dict(movement_type="RESTOCK", quantity_change=-3), dict(movement_type="ADJUSTMENT", quantity_change=0),
               dict(movement_type="SALE", quantity_change=1)]
        for kw in bad:
            with self.subTest(**kw), self.assertRaises(IntegrityError), transaction.atomic():
                StockMovement.objects.create(product=p, recorded_by=owner, **kw)


class PaginationTests(TestCase):
    """ISS-03: long lists are paged and bad page numbers don't crash."""

    def setUp(self):
        self.owner = make_user("owner@example.com", "OWNER")
        self.product = make_product(self.owner)
        StockMovement.objects.bulk_create([
            StockMovement(product=self.product, recorded_by=self.owner, movement_type="RESTOCK", quantity_change=1)
            for _ in range(30)])
        self.client.force_login(self.owner)

    def test_stock_log_pages(self):
        url = reverse("inventory:movement_list")
        self.assertEqual(len(self.client.get(url).context["movements"]), 25)
        resp = self.client.get(url + "?type=RESTOCK&page=2")
        self.assertEqual(len(resp.context["movements"]), 5)
        self.assertContains(resp, "Page 2 of 2")
        self.assertContains(resp, "type=RESTOCK&amp;page=1")

    def test_bad_page_numbers(self):
        url = reverse("inventory:movement_list")
        for page in ["abc", "0", "-1", "999"]:
            self.assertEqual(self.client.get(url + f"?page={page}").status_code, 200, page)
