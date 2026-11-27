from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Count, ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from accounts.decorators import role_required
from accounts.models import User

from django.core.exceptions import ValidationError
from django.core.paginator import Paginator

PAGE_SIZE = 25


def paginate(request, queryset):
    """ISS-03: page long lists. get_page() turns a bad ?page= value into page 1 or the last page."""
    page = Paginator(queryset, PAGE_SIZE).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return page, query.urlencode()

from . import services
from .forms import (CategoryForm, ProductFilterForm, ProductForm, StockFilterForm,
                    StockMovementEditForm, StockMovementForm)
from .models import Category, Product, StockMovement

OWNER = User.Role.OWNER


def _save_unique(form, save, field, message):
    """Save, turning a UNIQUE/CHECK violation from PostgreSQL into a form error instead of a 500.

    The form already checks for duplicates, but two people saving at the same moment can
    both pass that check; the database constraint is the final guard.
    """
    try:
        with transaction.atomic():
            save()
    except IntegrityError:
        form.add_error(field, message)
        return False
    return True


# ======================================================================= categories
@login_required
@require_safe
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
            if _save_unique(form, category.save, "name", "A category with this name already exists."):
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
            if _save_unique(form, form.save, "name", "A category with this name already exists."):
                messages.success(request, f"Category “{category.name}” saved.")
                return redirect("inventory:category_list")
        messages.error(request, "The category wasn't saved. Fix the highlighted fields.")
    if form.errors:
        category = Category.objects.get(pk=category.pk)
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
@require_safe
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
    page, page_query = paginate(request, products)
    return render(request, "inventory/product_list.html", {
        "form": form, "products": page.object_list, "page_obj": page, "page_query": page_query,
        "has_categories": Category.objects.exists(),
        "inactive_count": Product.objects.filter(is_active=False).count(),
        "filtered": bool(request.GET),
    })


@login_required
@require_safe
def product_detail(request, pk):
    product = get_object_or_404(Product.objects.select_related("category", "created_by"), pk=pk)
    history = visible_movements(request.user).filter(product=product)[:10]
    return render(request, "inventory/product_detail.html", {"product": product, "history": history})


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
            if _save_unique(form, product.save, "product_code", "Another product already uses this code."):
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
            if _save_unique(form, form.save, "product_code", "Another product already uses this code."):
                messages.success(request, f"Product “{product.name}” saved.")
                return redirect("inventory:product_detail", pk=product.pk)
        messages.error(request, "The product wasn't saved. Fix the highlighted fields.")
    if form.errors:
        product = Product.objects.get(pk=product.pk)  # show the saved name, not the rejected input
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
    return product.movements.exists()


# ======================================================================= stock movements
def visible_movements(user):
    """Owners see every stock entry; helpers see only the entries they recorded."""
    qs = StockMovement.objects.select_related("product", "recorded_by")
    return qs if user.is_owner else qs.filter(recorded_by=user)


@login_required
@require_safe
def movement_list(request):
    form = StockFilterForm(request.GET or None)
    movements = visible_movements(request.user)
    if form.is_valid():
        data = form.cleaned_data
        if data.get("q"):
            movements = movements.filter(Q(product__name__icontains=data["q"]) |
                                         Q(product__product_code__icontains=data["q"]))
        if data.get("type"):
            movements = movements.filter(movement_type=data["type"])
        if data.get("date_from"):
            movements = movements.filter(movement_date__date__gte=data["date_from"])
        if data.get("date_to"):
            movements = movements.filter(movement_date__date__lte=data["date_to"])
    page, page_query = paginate(request, movements)
    return render(request, "inventory/movement_list.html", {
        "form": form, "movements": page.object_list, "page_obj": page, "page_query": page_query,
        "filtered": bool(set(request.GET) - {"page"}),
    })


@login_required
@require_http_methods(["GET", "POST"])
def movement_create(request):
    initial = {}
    if request.method == "GET":
        if request.GET.get("product"):
            initial["product"] = request.GET["product"]
        if request.GET.get("type") in StockMovement.Type.values:
            initial["movement_type"] = request.GET["type"]
    form = StockMovementForm(request.POST or None, initial=initial)
    if request.method == "POST":
        if form.is_valid():
            data = form.cleaned_data
            try:
                movement = services.record_movement(
                    product=data["product"], user=request.user, movement_type=data["movement_type"],
                    quantity_change=data["quantity_change"], reason=data["reason"])
            except ValidationError as e:
                form.add_error(None, e)
            else:
                p = movement.product
                verb = "added to" if movement.is_increase else "removed from"
                messages.success(request, f"{movement.quantity_abs} {verb} {p.name}. Stock is now {p.stock_qty}.")
                if p.is_low_stock:
                    messages.warning(request, f"{p.name} is low on stock ({p.stock_qty} left, reorder level {p.reorder_level}).")
                if request.POST.get("next") == "product":
                    return redirect("inventory:product_detail", pk=p.pk)
                return redirect("inventory:movement_list")
        messages.error(request, "The stock change wasn't saved. Fix the highlighted fields.")
    return render(request, "inventory/movement_form.html", {
        "form": form, "from_product": bool(request.GET.get("product") or request.POST.get("next") == "product"),
        "has_products": Product.objects.active().exists(),
    })


@login_required
@require_http_methods(["GET", "POST"])
def movement_edit(request, pk):
    # A helper asking for someone else's entry gets a 404, as if it didn't exist.
    movement = get_object_or_404(visible_movements(request.user), pk=pk)
    form = StockMovementEditForm(request.POST or None, movement=movement)
    if request.method == "POST":
        if form.is_valid():
            try:
                services.update_movement(movement, quantity_change=form.cleaned_data["quantity_change"],
                                         reason=form.cleaned_data["reason"])
            except ValidationError as e:
                form.add_error(None, e)
            else:
                movement.product.refresh_from_db()
                messages.success(request, f"Stock entry saved. {movement.product.name} now has "
                                          f"{movement.product.stock_qty} in stock.")
                return redirect("inventory:movement_list")
        messages.error(request, "The stock entry wasn't saved. Fix the highlighted fields.")
    return render(request, "inventory/movement_edit.html", {"form": form, "movement": movement})


@login_required
@require_http_methods(["GET", "POST"])
def movement_delete(request, pk):
    movement = get_object_or_404(visible_movements(request.user), pk=pk)
    product = movement.product
    blocked = product.stock_qty - movement.quantity_change < 0
    if request.method == "POST":
        try:
            services.delete_movement(movement)
        except ValidationError as e:
            messages.error(request, e.messages[0])
            return redirect("inventory:movement_list")
        product.refresh_from_db()
        messages.success(request, f"Stock entry deleted. {product.name} now has {product.stock_qty} in stock.")
        return redirect("inventory:movement_list")
    sign = "-" if movement.is_increase else "+"
    return render(request, "inventory/confirm_delete.html", {
        "object_label": f"this {movement.get_movement_type_display().lower()} of {movement.quantity_abs} {product.name}",
        "confirm_note": f"Stock goes from {product.stock_qty} to {product.stock_qty - movement.quantity_change} "
                        f"({sign}{movement.quantity_abs}). This can't be undone.",
        "blocked": blocked,
        "blocked_reason": f"Some of these units have already left stock ({product.stock_qty} left), so deleting "
                          "this entry would put the product below zero. Record an adjustment instead.",
        "cancel_url": "inventory:movement_list",
    })
