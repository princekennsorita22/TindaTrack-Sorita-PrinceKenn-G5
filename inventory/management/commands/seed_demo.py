"""Create demo accounts and sample sari-sari store stock.

    python manage.py seed_demo

Safe to run more than once: existing accounts and products are left as they are.
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import User
from inventory import services
from inventory.models import Category, Product, StockMovement

DEMO_PASSWORD = "TindaDemo2026!"

ACCOUNTS = [
    ("owner@tindatrack.test", "Nena Cruz", User.Role.OWNER),
    ("helper@tindatrack.test", "Joy Reyes", User.Role.HELPER),
]

CATALOG = {
    "Canned goods": [("SARD-155", "Sardinas 155g", "can", "18.00", "23.00", 6, 30),
                     ("CORN-150", "Corned beef 150g", "can", "32.00", "40.00", 4, 3)],
    "Drinks": [("COLA-1.5", "Cola 1.5L", "bottle", "58.00", "70.00", 4, 12),
               ("KAPE-3N1", "Kape 3-in-1", "sachet", "7.50", "10.00", 20, 15)],
    "Rice and noodles": [("BIGAS-1K", "Bigas (per kilo)", "kilo", "46.00", "54.00", 10, 40),
                         ("PCAN-60", "Pancit canton 60g", "pack", "13.00", "17.00", 12, 0)],
}


class Command(BaseCommand):
    help = "Create demo owner/helper accounts and sample products with stock."

    @transaction.atomic
    def handle(self, *args, **options):
        users = {}
        for email, name, role in ACCOUNTS:
            user, created = User.objects.get_or_create(email=email, defaults={"full_name": name, "role": role})
            if created:
                user.set_password(DEMO_PASSWORD)
                user.save()
            users[role] = user
            self.stdout.write(f"{'Created' if created else 'Exists '}  {role:<6} {email}")
        owner, helper = users[User.Role.OWNER], users[User.Role.HELPER]

        for cat_name, items in CATALOG.items():
            category, _ = Category.objects.get_or_create(name=cat_name, defaults={"created_by": owner})
            for code, name, unit, cost, price, reorder, opening in items:
                product, created = Product.objects.get_or_create(product_code=code, defaults={
                    "category": category, "name": name, "unit": unit, "cost_price": Decimal(cost),
                    "selling_price": Decimal(price), "reorder_level": reorder, "created_by": owner})
                if created and opening and not StockMovement.objects.filter(product=product).exists():
                    services.record_movement(product=product, user=helper, movement_type="RESTOCK",
                                             quantity_change=opening, reason="Opening stock")
        self.stdout.write(self.style.SUCCESS(f"Done. Demo password for both accounts: {DEMO_PASSWORD}"))
