from django.urls import path

from . import views

app_name = "inventory"

urlpatterns = [
    path("categories/", views.category_list, name="category_list"),
    path("categories/new/", views.category_create, name="category_create"),
    path("categories/<int:pk>/edit/", views.category_edit, name="category_edit"),
    path("categories/<int:pk>/delete/", views.category_delete, name="category_delete"),
    path("products/", views.product_list, name="product_list"),
    path("products/new/", views.product_create, name="product_create"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("products/<int:pk>/edit/", views.product_edit, name="product_edit"),
    path("products/<int:pk>/toggle-active/", views.product_toggle_active, name="product_toggle_active"),
    path("products/<int:pk>/delete/", views.product_delete, name="product_delete"),
    path("stock/", views.movement_list, name="movement_list"),
    path("stock/new/", views.movement_create, name="movement_create"),
    path("stock/<int:pk>/edit/", views.movement_edit, name="movement_edit"),
    path("stock/<int:pk>/delete/", views.movement_delete, name="movement_delete"),
]
