from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.decorators import role_required
from accounts.models import User

from .forms import CategoryForm, ProductFilterForm, ProductForm
from .models import Category, Product

OWNER = User.Role.OWNER


# ======================================================================= categories
@login_required
def category_list(request):
    categories = Category.objects.annotate(product_count=Count("products")).select_related("created_by")
    return render(request, "inventory/category_list.html", {"categories": categories})


@role_required(OWNER)
@require_http_methods(["GET", "POST"])
def category_create(request):
    form = CategoryForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            category = form.save(commit=False)
            category.created_by = request.user
            category.save()
            messages.success(request, f"Category “{category.name}” added.")
            return redirect("inventory:category_list")
        messages.error(request, "The category wasn't added. Fix the highlighted fields.")
    return render(request, "inventory/category_form.html", {"form": form, "is_new": True})


@role_required(OWNER)
@require_http_methods(["GET", "POST"])
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    form = CategoryForm(request.POST or None, instance=category)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, f"Category “{category.name}” saved.")
            return redirect("inventory:category_list")
        messages.error(request, "The category wasn't saved. Fix the highlighted fields.")
    return render(request, "inventory/category_form.html", {"form": form, "category": category})


@role_required(OWNER)
@require_http_methods(["GET", "POST"])
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if request.method == "POST":
        try:
            category.delete()
        except ProtectedError:
            # BR-04: a category that still has products can't be deleted (FK ON DELETE RESTRICT).
            messages.error(request, f"“{category.name}” still has products, so it can't be deleted. "
                                    "Move or delete those products first.")
            return redirect("inventory:category_list")
        messages.success(request, f"Category “{category.name}” deleted.")
        return redirect("inventory:category_list")
    return render(request, "inventory/confirm_delete.html", {
        "object_label": f"the category “{category.name}”",
        "blocked": category.products.exists(),
        "blocked_reason": "This category still has products. Move or delete them first.",
        "cancel_url": "inventory:category_list",
    })


# ======================================================================= products
@login_required
def product_list(request):
    form = ProductFilterForm(request.GET or None)
    products = Product.objects.select_related("category")
    status = "active"
    if form.is_valid():
        data = form.cleaned_data
        status = data.get("status") or "active"
        if data.get("q"):
            products = products.filter(Q(name__icontains=data["q"]) | Q(product_code__icontains=data["q"]))
        if data.get("category"):
            products = products.filter(category=data["category"])
        if data.get("stock") == "low":
            products = products.low_stock()
        elif data.get("stock") == "out":
            products = products.filter(stock_qty=0)
    if status == "active":
        products = products.filter(is_active=True)
    elif status == "inactive":
        products = products.filter(is_active=False)
    return render(request, "inventory/product_list.html", {
        "form": form, "products": products,
        "has_categories": Category.objects.exists(),
        "inactive_count": Product.objects.filter(is_active=False).count(),
        "filtered": bool(request.GET),
    })


@login_required
def product_detail(request, pk):
    product = get_object_or_404(Product.objects.select_related("category", "created_by"), pk=pk)
    return render(request, "inventory/product_detail.html", {"product": product})


@role_required(OWNER)
@require_http_methods(["GET", "POST"])
def product_create(request):
    if not Category.objects.exists():
        messages.info(request, "Add a category first. Every product belongs to one category.")
        return redirect("inventory:category_create")
    form = ProductForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            product = form.save(commit=False)
            product.created_by = request.user
            product.save()
            messages.success(request, f"Product “{product.name}” added with 0 in stock.")
            return redirect("inventory:product_detail", pk=product.pk)
        messages.error(request, "The product wasn't added. Fix the highlighted fields.")
    return render(request, "inventory/product_form.html", {"form": form, "is_new": True})


@role_required(OWNER)
@require_http_methods(["GET", "POST"])
def product_edit(request, pk):
    # BR-03: only an owner may change prices, so the whole edit form is owner-only.
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, instance=product)
    if request.method == "POST":
        if form.is_valid():
            form.save()
            messages.success(request, f"Product “{product.name}” saved.")
            return redirect("inventory:product_detail", pk=product.pk)
        messages.error(request, "The product wasn't saved. Fix the highlighted fields.")
    return render(request, "inventory/product_form.html", {"form": form, "product": product})


@role_required(OWNER)
@require_POST
def product_toggle_active(request, pk):
    product = get_object_or_404(Product, pk=pk)
    product.is_active = not product.is_active
    product.save(update_fields=["is_active"])
    if product.is_active:
        messages.success(request, f"“{product.name}” is active again.")
    else:
        messages.success(request, f"“{product.name}” deactivated. It stays in your records but is hidden from the product list.")
    return redirect("inventory:product_detail", pk=product.pk)


@role_required(OWNER)
@require_http_methods(["GET", "POST"])
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
    has_history = _has_history(product)
    if request.method == "POST":
        try:
            product.delete()
        except ProtectedError:
            # BR-08: a product with stock or sales history can only be deactivated.
            messages.error(request, f"“{product.name}” has stock history, so it can't be deleted. "
                                    "Deactivate it instead.")
            return redirect("inventory:product_detail", pk=product.pk)
        messages.success(request, f"Product “{product.name}” deleted.")
        return redirect("inventory:product_list")
    return render(request, "inventory/confirm_delete.html", {
        "object_label": f"the product “{product.name}”",
        "blocked": has_history,
        "blocked_reason": "This product has stock history. Deactivate it instead so its records are kept.",
        "cancel_url": "inventory:product_detail", "cancel_pk": product.pk,
    })


def _has_history(product):
    return hasattr(product, "movements") and product.movements.exists()
