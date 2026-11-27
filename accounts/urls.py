from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register, name="register"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("owner/dashboard/", views.owner_dashboard, name="owner_dashboard"),
    path("helper/dashboard/", views.helper_dashboard, name="helper_dashboard"),
    path("owner/team/", views.team, name="team"),
    path("owner/team/<int:pk>/role/", views.team_change_role, name="team_change_role"),
    path("profile/", views.profile, name="profile"),
    path("profile/edit/", views.profile_edit, name="profile_edit"),
    path("profile/password/", views.PasswordChangeView.as_view(), name="password_change"),
]
