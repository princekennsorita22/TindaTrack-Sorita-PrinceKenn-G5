from django.contrib import admin

from .models import Category, Product, StockMovement


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "created_by", "created_at")
    search_fields = ("name",)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("product_code", "name", "category", "selling_price", "stock_qty", "reorder_level", "is_active")
    list_filter = ("category", "is_active")
    search_fields = ("product_code", "name")
    readonly_fields = ("stock_qty",)


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    """Read-only here: stock changes must go through the app so stock_qty stays correct."""

    list_display = ("movement_date", "product", "movement_type", "quantity_change", "recorded_by", "reason")
    list_filter = ("movement_type",)
    search_fields = ("product__name", "product__product_code", "reason")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
