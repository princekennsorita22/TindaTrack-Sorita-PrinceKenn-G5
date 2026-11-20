from decimal import Decimal

from accounts.models import User
from inventory.models import Category, Product

PASSWORD = "Sari-Sari-2026!"


def make_user(email, role):
    return User.objects.create_user(email=email, password=PASSWORD, full_name=email.split("@")[0].title(), role=role)


def make_product(owner, code="SARD-155", name="Sardinas 155g", stock=0, reorder=5, category=None, **kw):
    category = category or Category.objects.get_or_create(name="Canned goods", defaults={"created_by": owner})[0]
    return Product.objects.create(category=category, product_code=code, name=name, unit="can",
                                  cost_price=Decimal("18.00"), selling_price=Decimal("23.00"),
                                  stock_qty=stock, reorder_level=reorder, created_by=owner, **kw)
