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

    q = forms.CharField(required=False, label="Search",
                        widget=forms.TextInput(attrs={"placeholder": "Name or code", "type": "search"}))
    category = forms.ModelChoiceField(queryset=Category.objects.all(), required=False,
                                      empty_label="All categories")
    stock = forms.ChoiceField(choices=STOCK_CHOICES, required=False, label="Stock")
    status = forms.ChoiceField(choices=STATUS_CHOICES, required=False, label="Status")

