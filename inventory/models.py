from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower, Upper


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
        constraints = [
            # "Drinks" and "drinks" count as the same category (BR-04), checked by PostgreSQL too.
            models.UniqueConstraint(Lower("name"), name="categories_name_unique_ci"),
            models.CheckConstraint(condition=~Q(name=""), name="categories_name_not_blank"),
        ]

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
            models.CheckConstraint(condition=Q(product_code=Upper("product_code")) & ~Q(product_code=""),
                                   name="products_code_uppercase"),
            models.CheckConstraint(condition=~Q(name=""), name="products_name_not_blank"),
        ]

    def __str__(self):
        return f"{self.name} ({self.product_code})"

    @property
    def is_low_stock(self):
        return self.stock_qty <= self.reorder_level

    @property
    def margin(self):
        return self.selling_price - self.cost_price


class StockMovement(models.Model):
    """The `stock_movements` table from the SDD (BR-10 to BR-12).

    Every change to a product's stock is saved here, with the user who made it.
    Create, update and delete go through inventory/services.py so the product's
    stock_qty always matches the log.
    """

    class Type(models.TextChoices):
        RESTOCK = "RESTOCK", "Restock"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    movement_id = models.BigAutoField(primary_key=True)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    related_name="stock_movements", db_column="user_id")
    movement_type = models.CharField(max_length=10, choices=Type.choices)
    quantity_change = models.IntegerField(help_text="Positive adds units, negative removes them.")
    reason = models.CharField(max_length=150, blank=True)
    movement_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "stock_movements"
        ordering = ["-movement_date", "-movement_id"]
        constraints = [
            models.CheckConstraint(condition=Q(movement_type__in=["RESTOCK", "ADJUSTMENT"]),
                                   name="stock_movements_type_valid"),
            models.CheckConstraint(condition=~Q(quantity_change=0), name="stock_movements_quantity_not_zero"),
            models.CheckConstraint(condition=~Q(movement_type="RESTOCK") | Q(quantity_change__gt=0),
                                   name="stock_movements_restock_positive"),
            models.CheckConstraint(condition=Q(quantity_change__gte=-10000) & Q(quantity_change__lte=10000),
                                   name="stock_movements_quantity_in_range"),
            # An adjustment must say why (damaged, expired, miscounted).
            models.CheckConstraint(condition=~Q(movement_type="ADJUSTMENT") | ~Q(reason=""),
                                   name="stock_movements_adjustment_has_reason"),
        ]

    def __str__(self):
        return f"{self.get_movement_type_display()} {self.quantity_change:+d} {self.product.name}"

    @property
    def is_increase(self):
        return self.quantity_change > 0

    @property
    def quantity_abs(self):
        return abs(self.quantity_change)
