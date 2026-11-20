from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.messages.views import SuccessMessageMixin
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_http_methods

from .decorators import role_required
from .forms import LoginForm, ProfileForm, RegisterForm, StyledPasswordChangeForm
from .models import User


# ---------------------------------------------------------------- registration
@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"Account created for {user.email}. Log in to continue.")
            return redirect("accounts:login")
        messages.error(request, "Your account wasn't created. Fix the highlighted fields and try again.")
    else:
        form = RegisterForm()
    return render(request, "accounts/register.html", {"form": form})


# ---------------------------------------------------------------- login/logout
class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Welcome back, {self.request.user.first_name_display}.")
        return response


class LogoutView(auth_views.LogoutView):
    """POST-only (Django default). Ends the session, then shows the login page."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        messages.info(request, "You've logged out.")
        return response


# ---------------------------------------------------------------- dashboards
@login_required
def dashboard(request):
    """Sends each user to the dashboard for their role."""
    if request.user.is_owner:
        return redirect("accounts:owner_dashboard")
    return redirect("accounts:helper_dashboard")


def _low_stock():
    from inventory.models import Product
    return Product.objects.active().low_stock().select_related("category").order_by("stock_qty", "name")


@role_required(User.Role.OWNER)
def owner_dashboard(request):
    from inventory.models import Category, Product, StockMovement
    low = _low_stock()
    return render(request, "accounts/dashboard_owner.html", {
        "low_count": low.count(),
        "low_items": low[:6],
        "active_products": Product.objects.active().count(),
        "has_categories": Category.objects.exists(),
        "has_products": Product.objects.exists(),
        "has_movements": StockMovement.objects.exists(),
        "recent_movements": StockMovement.objects.select_related("product", "recorded_by")[:6],
    })


@role_required(User.Role.HELPER)
def helper_dashboard(request):
    from inventory.models import StockMovement
    return render(request, "accounts/dashboard_helper.html", {
        "low_items": _low_stock()[:8],
        "my_recent": StockMovement.objects.filter(recorded_by=request.user).select_related("product")[:5],
    })


# ---------------------------------------------------------------- profile
# Both views use request.user, never an id from the URL, so a user can only
# ever see or change their own profile.
@login_required
def profile(request):
    return render(request, "accounts/profile.html", {"profile_user": request.user})


@login_required
@require_http_methods(["GET", "POST"])
def profile_edit(request):
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, "Profile saved.")
            return redirect("accounts:profile")
        messages.error(request, "Your profile wasn't saved. Fix the highlighted fields and try again.")
    else:
        form = ProfileForm(instance=request.user)
    return render(request, "accounts/profile_edit.html", {"form": form})


class PasswordChangeView(SuccessMessageMixin, auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = StyledPasswordChangeForm
    success_url = reverse_lazy("accounts:profile")
    success_message = "Password changed."


def permission_denied(request, exception=None):
    return render(request, "403.html", status=403)
