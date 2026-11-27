"""URLs used only by the tests to trigger a server error."""
from django.urls import include, path


def boom(request):
    raise RuntimeError("Simulated crash for the 500-page test")


urlpatterns = [
    path("boom/", boom),
    path("", include("tindatrack.urls")),
]

handler500 = "accounts.views.server_error"
