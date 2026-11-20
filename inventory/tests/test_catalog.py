from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from inventory.models import Category, Product

from .helpers import make_product, make_user


class CatalogAccessTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com", "OWNER")
        self.helper = make_user("helper@example.com", "HELPER")
        self.product = make_product(self.owner)

    def test_logged_out_users_go_to_login(self):
        for url in [reverse("inventory:product_list"), reverse("inventory:category_list"),
                    reverse("inventory:product_detail", args=[self.product.pk])]:
            resp = self.client.get(url)
            self.assertRedirects(resp, f"{reverse('accounts:login')}?next={url}")

    def test_helper_can_view_but_not_change(self):
        self.client.force_login(self.helper)
        self.assertEqual(self.client.get(reverse("inventory:product_list")).status_code, 200)
        resp = self.client.get(reverse("inventory:product_detail", args=[self.product.pk]))
        self.assertNotContains(resp, "Cost price")
        for url in [reverse("inventory:product_create"), reverse("inventory:category_create"),
                    reverse("inventory:product_edit", args=[self.product.pk]),
                    reverse("inventory:product_delete", args=[self.product.pk]),
                    reverse("inventory:category_delete", args=[self.product.category.pk])]:
            self.assertEqual(self.client.get(url).status_code, 403, url)
        resp = self.client.post(reverse("inventory:product_edit", args=[self.product.pk]),
                                {"selling_price": "1.00"})
        self.assertEqual(resp.status_code, 403)
        self.product.refresh_from_db()
        self.assertEqual(str(self.product.selling_price), "23.00")


class CategoryCrudTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com", "OWNER")
        self.client.force_login(self.owner)

    def test_create_links_to_user(self):
        resp = self.client.post(reverse("inventory:category_create"),
                                {"name": "  Drinks ", "description": "Softdrinks and juice"}, follow=True)
        self.assertContains(resp, "Category “Drinks” added.")
        self.assertEqual(Category.objects.get().created_by, self.owner)

    def test_duplicate_name_any_case(self):
        Category.objects.create(name="Drinks", created_by=self.owner)
        resp = self.client.post(reverse("inventory:category_create"), {"name": "DRINKS"})
        self.assertFormError(resp.context["form"], "name", "A category with this name already exists.")

    def test_required_name(self):
        resp = self.client.post(reverse("inventory:category_create"), {"name": ""})
        self.assertIn("name", resp.context["form"].errors)
        self.assertContains(resp, "wasn&#x27;t added")

    def test_edit(self):
        c = Category.objects.create(name="Drink", created_by=self.owner)
        self.client.post(reverse("inventory:category_edit", args=[c.pk]), {"name": "Drinks"})
        c.refresh_from_db()
        self.assertEqual(c.name, "Drinks")

    def test_delete_empty_category(self):
        c = Category.objects.create(name="Snacks", created_by=self.owner)
        self.client.post(reverse("inventory:category_delete", args=[c.pk]))
        self.assertFalse(Category.objects.exists())

    def test_cannot_delete_category_with_products(self):
        p = make_product(self.owner)
        resp = self.client.post(reverse("inventory:category_delete", args=[p.category.pk]), follow=True)
        self.assertContains(resp, "still has products")
        self.assertTrue(Category.objects.filter(pk=p.category.pk).exists())


class ProductCrudTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com", "OWNER")
        self.client.force_login(self.owner)
        self.cat = Category.objects.create(name="Canned goods", created_by=self.owner)

    def data(self, **kw):
        d = {"product_code": "sard-155", "name": "Sardinas 155g", "category": self.cat.pk, "unit": "can",
             "cost_price": "18.00", "selling_price": "23.00", "reorder_level": "6"}
        d.update(kw)
        return d

    def test_create_product(self):
        resp = self.client.post(reverse("inventory:product_create"), self.data(), follow=True)
        p = Product.objects.get()
        self.assertRedirects(resp, reverse("inventory:product_detail", args=[p.pk]))
        self.assertEqual(p.product_code, "SARD-155")
        self.assertEqual(p.stock_qty, 0)
        self.assertEqual(p.created_by, self.owner)
        self.assertContains(resp, "added with 0 in stock")

    def test_validation(self):
        make_product(self.owner, code="SARD-155", category=self.cat)
        resp = self.client.post(reverse("inventory:product_create"),
                                self.data(selling_price="0", cost_price="-1", reorder_level="-2", name=""))
        errors = resp.context["form"].errors
        for f in ["product_code", "selling_price", "cost_price", "reorder_level", "name"]:
            self.assertIn(f, errors, f)
        resp = self.client.post(reverse("inventory:product_create"), self.data(product_code="bad code!"))
        self.assertIn("Use only letters", str(resp.context["form"].errors))

    def test_create_without_category_redirects(self):
        self.cat.delete()
        resp = self.client.get(reverse("inventory:product_create"))
        self.assertRedirects(resp, reverse("inventory:category_create"))

    def test_edit_price(self):
        p = make_product(self.owner, category=self.cat)
        self.client.post(reverse("inventory:product_edit", args=[p.pk]),
                         self.data(product_code="SARD-155", selling_price="25.50"))
        p.refresh_from_db()
        self.assertEqual(str(p.selling_price), "25.50")

    def test_deactivate_and_filter(self):
        p = make_product(self.owner, category=self.cat)
        self.client.post(reverse("inventory:product_toggle_active", args=[p.pk]))
        p.refresh_from_db()
        self.assertFalse(p.is_active)
        self.client.get(reverse("inventory:product_detail", args=[p.pk]))  # shows and clears the flash message
        self.assertNotContains(self.client.get(reverse("inventory:product_list")), "Sardinas")
        self.assertContains(self.client.get(reverse("inventory:product_list") + "?status=inactive"), "Sardinas")

    def test_search_and_low_stock_filter(self):
        make_product(self.owner, category=self.cat, stock=50)
        make_product(self.owner, code="KAPE-3IN1", name="Kape 3-in-1", stock=2, category=self.cat)
        url = reverse("inventory:product_list")
        self.assertNotContains(self.client.get(url + "?q=kape"), "Sardinas")
        resp = self.client.get(url + "?stock=low")
        self.assertContains(resp, "Kape 3-in-1")
        self.assertNotContains(resp, "Sardinas")

    def test_delete_product_without_history(self):
        p = make_product(self.owner, category=self.cat)
        self.client.post(reverse("inventory:product_delete", args=[p.pk]))
        self.assertFalse(Product.objects.exists())

    def test_database_checks(self):
        p = make_product(self.owner, category=self.cat)
        for field, value in [("selling_price", 0), ("cost_price", -1), ("stock_qty", -1), ("reorder_level", -1)]:
            with self.subTest(field=field), self.assertRaises(IntegrityError), transaction.atomic():
                Product.objects.filter(pk=p.pk).update(**{field: value})
