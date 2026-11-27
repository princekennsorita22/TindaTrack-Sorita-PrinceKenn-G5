from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView

from accounts.views import protected_media

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="accounts:dashboard", permanent=False), name="home"),
    path("admin/", admin.site.urls),
    path("", include("accounts.urls")),
    path("inventory/", include("inventory.urls")),
    # ISS-02: uploaded photos are served by a login-protected view in every mode.
    re_path(r"^media/(?P<path>.+)$", protected_media, name="media"),
]

handler403 = "accounts.views.permission_denied"
