import re

from django import forms

from .models import Category, Product


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ("name", "description")
        labels = {"name": "Category name"}
        help_texts = {"description": "Optional. A short note about what goes in this category."}

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if not name:
            raise forms.ValidationError("Enter a category name.")
        # Unique regardless of capital letters: "Drinks" and "drinks" are the same category.
        clash = Category.objects.filter(name__iexact=name).exclude(pk=self.instance.pk)
        if clash.exists():
            raise forms.ValidationError("A category with this name already exists.")
        return name


class ProductForm(forms.ModelForm):
    """Create/edit a product. Stock is not here: it changes only through restocks and adjustments."""

    class Meta:
        model = Product
        fields = ("product_code", "name", "category", "unit", "cost_price", "selling_price", "reorder_level")
        labels = {"product_code": "Product code", "cost_price": "Cost price (₱)",
                  "selling_price": "Selling price (₱)", "reorder_level": "Reorder level"}
        help_texts = {
            "product_code": "Letters, numbers and dashes, up to 20 characters. Example: SARD-155",
            "cost_price": "What you pay the supplier for one unit.",
            "selling_price": "What a customer pays for one unit.",
            "reorder_level": "The product is flagged as low on stock at or below this number.",
        }
        widgets = {
            "cost_price": forms.NumberInput(attrs={"step": "0.01", "min": "0", "inputmode": "decimal"}),
            "selling_price": forms.NumberInput(attrs={"step": "0.01", "min": "0.01", "inputmode": "decimal"}),
            "reorder_level": forms.NumberInput(attrs={"min": "0", "inputmode": "numeric"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.all()
        self.fields["category"].empty_label = "Choose a category"
        self.fields["category"].error_messages["required"] = "Choose a category. Add one first if the list is empty."

    def clean_product_code(self):
        code = self.cleaned_data["product_code"].strip().upper()
        if not re.fullmatch(r"[A-Z0-9-]+", code):
            raise forms.ValidationError("Use only letters, numbers and dashes.")
        if Product.objects.filter(product_code__iexact=code).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Another product already uses this code.")
        return code

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        if not name:
            raise forms.ValidationError("Enter the product name.")
        return name

    def clean_selling_price(self):
        price = self.cleaned_data["selling_price"]
        if price is not None and price <= 0:
            raise forms.ValidationError("The selling price must be more than ₱0.")
        return price

    def clean_cost_price(self):
        cost = self.cleaned_data["cost_price"]
        if cost is not None and cost < 0:
            raise forms.ValidationError("The cost price can't be negative.")
        return cost


class _NoColonForm(forms.Form):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)


class ProductFilterForm(_NoColonForm):
    STOCK_CHOICES = [("", "Any stock level"), ("low", "Low on stock"), ("out", "Out of stock")]
    STATUS_CHOICES = [("active", "Active"), ("inactive", "Deactivated"), ("all", "All")]

    q = forms.CharField(required=False, label="Search", max_length=100,
                        widget=forms.TextInput(attrs={"placeholder": "Name or code", "type": "search"}))
    category = forms.ModelChoiceField(queryset=Category.objects.all(), required=False,
                                      empty_label="All categories")
    stock = forms.ChoiceField(choices=STOCK_CHOICES, required=False, label="Stock")
    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False, label="Status")


# ======================================================================= stock movements
from .models import StockMovement  # noqa: E402

MAX_QTY = 10000


class _QuantityMixin(forms.Form):
    """Shared quantity / direction / reason fields and the signed quantity they produce."""

    DIRECTION_CHOICES = [("add", "Add units"), ("remove", "Remove units")]

    direction = forms.ChoiceField(choices=DIRECTION_CHOICES, initial="remove", required=False,
                                  label="Add or remove", widget=forms.RadioSelect)
    quantity = forms.IntegerField(min_value=1, max_value=MAX_QTY, label="Quantity",
                                  error_messages={"min_value": "Enter at least 1.",
                                                  "max_value": f"Enter {MAX_QTY:,} or less.",
                                                  "required": "Enter how many units.",
                                                  "invalid": "Enter a whole number."},
                                  widget=forms.NumberInput(attrs={"min": "1", "inputmode": "numeric"}))
    reason = forms.CharField(max_length=150, required=False, label="Reason",
                             help_text="Needed for adjustments. Optional for restocks.",
                             widget=forms.TextInput(attrs={"placeholder": "e.g. Delivery from supplier"}))

    def movement_type_value(self):
        raise NotImplementedError

    def clean_reason(self):
        return " ".join(self.cleaned_data.get("reason", "").split())

    def clean(self):
        cleaned = super().clean()
        mtype = self.movement_type_value()
        qty = cleaned.get("quantity")
        if mtype == StockMovement.Type.ADJUSTMENT:
            if cleaned.get("direction") not in ("add", "remove"):
                self.add_error("direction", "Choose whether to add or remove units.")
            if not cleaned.get("reason"):
                self.add_error("reason", "Say why the stock is being adjusted, e.g. damaged, expired or miscounted.")
        if qty:
            remove = mtype == StockMovement.Type.ADJUSTMENT and cleaned.get("direction") == "remove"
            cleaned["quantity_change"] = -qty if remove else qty
        return cleaned


class StockMovementForm(_QuantityMixin):
    product = forms.ModelChoiceField(queryset=Product.objects.none(), label="Product",
                                     empty_label="Choose a product",
                                     error_messages={"required": "Choose a product."})
    movement_type = forms.ChoiceField(choices=StockMovement.Type.choices, initial=StockMovement.Type.RESTOCK,
                                      label="Type", widget=forms.RadioSelect)

    field_order = ["movement_type", "product", "direction", "quantity", "reason"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.active().select_related("category")
        self.fields["product"].label_from_instance = (
            lambda p: f"{p.name} ({p.product_code}) — {p.stock_qty} in stock")

    def movement_type_value(self):
        return self.cleaned_data.get("movement_type")

    def clean(self):
        cleaned = super().clean()
        product, change = cleaned.get("product"), cleaned.get("quantity_change")
        if product and change and product.stock_qty + change < 0:
            self.add_error("quantity", f"Only {product.stock_qty} in stock, so you can remove at most {product.stock_qty}.")
        return cleaned


class StockMovementEditForm(_QuantityMixin):
    """Edit the quantity and reason of an entry. Product and type stay fixed."""

    def __init__(self, *args, movement, **kwargs):
        self.movement = movement
        if not kwargs.get("data"):
            kwargs.setdefault("initial", {
                "quantity": movement.quantity_abs, "reason": movement.reason,
                "direction": "add" if movement.is_increase else "remove",
            })
        super().__init__(*args, **kwargs)
        if movement.movement_type == StockMovement.Type.RESTOCK:
            del self.fields["direction"]

    def movement_type_value(self):
        return self.movement.movement_type

    def clean(self):
        cleaned = super().clean()
        change = cleaned.get("quantity_change")
        product = self.movement.product
        if change:
            new_stock = product.stock_qty - self.movement.quantity_change + change
            if new_stock < 0:
                self.add_error("quantity", f"This would leave {product.name} below zero "
                                           f"({product.stock_qty} in stock now).")
        return cleaned


class StockFilterForm(_NoColonForm):
    TYPE_CHOICES = [("", "All types")] + list(StockMovement.Type.choices)

    q = forms.CharField(required=False, label="Product", max_length=100,
                        widget=forms.TextInput(attrs={"placeholder": "Name or code", "type": "search"}))
    type = forms.ChoiceField(choices=TYPE_CHOICES, required=False, label="Type")
    date_from = forms.DateField(required=False, label="From", widget=forms.DateInput(attrs={"type": "date"}))
    date_to = forms.DateField(required=False, label="To", widget=forms.DateInput(attrs={"type": "date"}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("date_from") and cleaned.get("date_to") and cleaned["date_from"] > cleaned["date_to"]:
            raise forms.ValidationError("The From date must be on or before the To date.")
        return cleaned
