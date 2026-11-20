from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q


class Category(models.Model):
    """The `categories` table from the SDD (BR-04)."""

    category_id = models.BigAutoField(primary_key=True)
    name = models.CharField(max_length=50, unique=True,
                            error_messages={"unique": "A category with this name already exists."})
    description = models.CharField(max_length=150, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="categories_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "categories"
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class ProductQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def low_stock(self):
        """BR-09: stock at or below the reorder level."""
        return self.filter(stock_qty__lte=F("reorder_level"))


class Product(models.Model):
    """The `products` table from the SDD (BR-05 to BR-09)."""

    class Unit(models.TextChoices):
        PIECE = "piece", "Piece"
        PACK = "pack", "Pack"
        BOTTLE = "bottle", "Bottle"
        CAN = "can", "Can"
        SACHET = "sachet", "Sachet"
        KILO = "kilo", "Kilo"

    product_id = models.BigAutoField(primary_key=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    product_code = models.CharField(max_length=20, unique=True,
                                    error_messages={"unique": "Another product already uses this code."})
    name = models.CharField(max_length=100)
    unit = models.CharField(max_length=20, choices=Unit.choices, default=Unit.PIECE)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2,
                                     validators=[MinValueValidator(Decimal("0"))])
    selling_price = models.DecimalField(max_digits=10, decimal_places=2,
                                        validators=[MinValueValidator(Decimal("0.01"))])
    # Never edited directly: it only changes through stock movements.
    stock_qty = models.IntegerField(default=0)
    reorder_level = models.IntegerField(default=5, validators=[MinValueValidator(0)])
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                   related_name="products_created")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = ProductQuerySet.as_manager()

    class Meta:
        db_table = "products"
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(condition=Q(selling_price__gt=0), name="products_selling_price_positive"),
            models.CheckConstraint(condition=Q(cost_price__gte=0), name="products_cost_price_not_negative"),
            models.CheckConstraint(condition=Q(stock_qty__gte=0), name="products_stock_qty_not_negative"),
            models.CheckConstraint(condition=Q(reorder_level__gte=0), name="products_reorder_level_not_negative"),
        ]

    def __str__(self):
        return f"{self.name} ({self.product_code})"

    @property
    def is_low_stock(self):
        return self.stock_qty <= self.reorder_level

    @property
    def margin(self):
        return self.selling_price - self.cost_price
