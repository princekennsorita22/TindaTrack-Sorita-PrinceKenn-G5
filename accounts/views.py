import mimetypes
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, Http404
from django.utils._os import safe_join
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.messages.views import SuccessMessageMixin
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from .decorators import role_required
from .forms import LoginForm, ProfileForm, RegisterForm, RoleChangeForm, StyledPasswordChangeForm
from .models import User


# ---------------------------------------------------------------- registration
@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save(commit=False)
                    # ISS-01: the very first account sets up the store and becomes its owner.
                    # Every later sign-up is a helper; an owner can promote them on the Team page.
                    is_first = not User.objects.filter(role=User.Role.OWNER).exists()
                    user.role = User.Role.OWNER if is_first else User.Role.HELPER
                    user.save()
            except IntegrityError:
                # Someone registered the same email a moment earlier (UNIQUE in PostgreSQL).
                form.add_error("email", "An account with this email already exists. Log in instead.")
                messages.error(request, "Your account wasn't created. Fix the highlighted fields and try again.")
                return render(request, "accounts/register.html", {"form": form})
            if is_first:
                messages.success(request, f"Store owner account created for {user.email}. Log in to continue.")
            else:
                messages.success(request, f"Helper account created for {user.email}. Log in to continue. "
                                          "The store owner can change your role.")
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
@require_safe
def dashboard(request):
    """Sends each user to the dashboard for their role."""
    if request.user.is_owner:
        return redirect("accounts:owner_dashboard")
    return redirect("accounts:helper_dashboard")


def _low_stock():
    from inventory.models import Product
    return Product.objects.active().low_stock().select_related("category").order_by("stock_qty", "name")


@role_required(User.Role.OWNER)
@require_safe
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
@require_safe
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
@require_safe
def profile(request):
    return render(request, "accounts/profile.html", {"profile_user": request.user})


@login_required
@require_http_methods(["GET", "POST"])
def profile_edit(request):
    # Edit a fresh copy of the user. A ModelForm writes the submitted values onto its
    # instance while validating, so editing request.user directly would show rejected
    # values (like a taken email) in the sidebar when the form has errors.
    me = User.objects.get(pk=request.user.pk)
    old_photo = me.profile_photo.name
    if request.method == "POST":
        form = ProfileForm(request.POST, request.FILES, instance=me)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
                    if old_photo and old_photo != user.profile_photo.name:
                        # Remove the replaced or cleared photo only after the save is committed.
                        storage = user.profile_photo.storage
                        transaction.on_commit(lambda: storage.delete(old_photo))
            except IntegrityError:
                form.add_error("email", "Another account already uses this email.")
            else:
                messages.success(request, "Profile saved.")
                return redirect("accounts:profile")
        messages.error(request, "Your profile wasn't saved. Fix the highlighted fields and try again.")
    else:
        form = ProfileForm(instance=me)
    return render(request, "accounts/profile_edit.html", {"form": form})


class PasswordChangeView(SuccessMessageMixin, auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    form_class = StyledPasswordChangeForm
    success_url = reverse_lazy("accounts:profile")
    success_message = "Password changed."


# ---------------------------------------------------------------- team (owner only)
@role_required(User.Role.OWNER)
@require_safe
def team(request):
    members = User.objects.filter(is_active=True).order_by("role", "full_name")
    return render(request, "accounts/team.html", {"members": members, "role_choices": User.Role.choices})


@role_required(User.Role.OWNER)
@require_POST
def team_change_role(request, pk):
    member = get_object_or_404(User, pk=pk, is_active=True)
    form = RoleChangeForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Choose a valid role.")
        return redirect("accounts:team")
    new_role = form.cleaned_data["role"]
    if member == request.user and new_role != User.Role.OWNER:
        messages.error(request, "You can't remove your own owner role. Ask another owner to do it.")
        return redirect("accounts:team")
    if member.role == new_role:
        messages.info(request, f"{member.full_name} is already a {member.get_role_display().lower()}.")
        return redirect("accounts:team")
    member.role = new_role
    member.save(update_fields=["role"])
    messages.success(request, f"{member.full_name} is now a {member.get_role_display().lower()}.")
    return redirect("accounts:team")


def permission_denied(request, exception=None):
    return render(request, "403.html", status=403)


def csrf_failure(request, reason=""):
    return render(request, "403_csrf.html", status=403)


def page_not_found(request, exception=None):
    return render(request, "404.html", status=404)


def bad_request(request, exception=None):
    return render(request, "400.html", status=400)


def server_error(request):
    # No request context here on purpose: if the error came from the database or a
    # context processor, rendering the normal layout could fail again.
    from django.template import loader
    from django.http import HttpResponseServerError
    return HttpResponseServerError(loader.get_template("500.html").render())


# ---------------------------------------------------------------- uploaded files
@login_required
@require_safe
def protected_media(request, path):
    """ISS-02: serve uploaded profile photos through Django in every mode, not only DEBUG.

    Only logged-in users can load them, and safe_join blocks paths like ../../.env.
    """
    try:
        full_path = Path(safe_join(settings.MEDIA_ROOT, path))
    except SuspiciousFileOperation:
        raise Http404("File not found.")
    if not full_path.is_file():
        raise Http404("File not found.")
    content_type, _ = mimetypes.guess_type(full_path.name)
    if content_type not in ("image/jpeg", "image/png", "image/webp"):
        raise Http404("File not found.")
    response = FileResponse(full_path.open("rb"), content_type=content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Cache-Control"] = "private, max-age=3600"
    return response
