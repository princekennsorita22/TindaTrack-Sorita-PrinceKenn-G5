"""Stock changes. Each function runs in one database transaction and locks the
product row (SELECT ... FOR UPDATE), so two people saving at the same time can't
leave stock_qty out of step with the stock log."""

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Product, StockMovement


def _check_rules(movement_type, quantity_change, product, new_stock):
    if quantity_change == 0:
        raise ValidationError("The quantity can't be zero.")  # BR-11
    if movement_type == StockMovement.Type.RESTOCK and quantity_change < 0:
        raise ValidationError("A restock must add units.")  # BR-11
    if new_stock < 0:  # BR-12
        raise ValidationError(
            f"This would leave {product.name} below zero. Only {product.stock_qty} "
            f"{product.get_unit_display().lower()}{'s' if product.stock_qty != 1 else ''} in stock."
        )


@transaction.atomic
def record_movement(*, product, user, movement_type, quantity_change, reason=""):
    product = Product.objects.select_for_update().get(pk=product.pk)
    if not product.is_active:
        raise ValidationError(f"{product.name} is deactivated. Reactivate it before changing its stock.")
    new_stock = product.stock_qty + quantity_change
    _check_rules(movement_type, quantity_change, product, new_stock)
    product.stock_qty = new_stock
    product.save(update_fields=["stock_qty"])
    return StockMovement.objects.create(product=product, recorded_by=user, movement_type=movement_type,
                                        quantity_change=quantity_change, reason=reason)


@transaction.atomic
def update_movement(movement, *, quantity_change, reason):
    product = Product.objects.select_for_update().get(pk=movement.product_id)
    new_stock = product.stock_qty - movement.quantity_change + quantity_change
    _check_rules(movement.movement_type, quantity_change, product, new_stock)
    product.stock_qty = new_stock
    product.save(update_fields=["stock_qty"])
    movement.quantity_change = quantity_change
    movement.reason = reason
    movement.save(update_fields=["quantity_change", "reason"])
    return movement


@transaction.atomic
def delete_movement(movement):
    """Undo a movement: its units are taken back out of (or put back into) stock."""
    product = Product.objects.select_for_update().get(pk=movement.product_id)
    new_stock = product.stock_qty - movement.quantity_change
    if new_stock < 0:
        raise ValidationError(
            f"Some of these units have already left stock, so deleting this entry would put "
            f"{product.name} below zero. Record an adjustment instead."
        )
    product.stock_qty = new_stock
    product.save(update_fields=["stock_qty"])
    movement.delete()
