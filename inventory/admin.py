from django.contrib import admin

from .models import Category, Product


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
