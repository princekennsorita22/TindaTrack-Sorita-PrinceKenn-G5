from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse

from .models import User

PASSWORD = "Sari-Sari-2026!"


def make_user(email, role, password=PASSWORD, name="Test User"):
    return User.objects.create_user(email=email, password=password, full_name=name, role=role)


class RegistrationTests(TestCase):
    url = reverse("accounts:register")

    def post(self, **overrides):
        data = {"full_name": "Nena Cruz", "email": "nena@example.com", "contact_number": "09171234567",
                "role": "OWNER", "password1": PASSWORD, "password2": PASSWORD}
        data.update(overrides)
        return self.client.post(self.url, data, follow=True)

    def test_register_success_hashes_password(self):
        resp = self.post()
        self.assertRedirects(resp, reverse("accounts:login"))
        user = User.objects.get(email="nena@example.com")
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
        self.assertTrue(user.check_password(PASSWORD))
        self.assertIn("Account created", [str(m) for m in get_messages(resp.wsgi_request)][0])

    def test_required_fields(self):
        resp = self.post(full_name="", email="")
        self.assertEqual(resp.status_code, 200)
        self.assertFormError(resp.context["form"], "full_name", "This field is required.")
        self.assertFormError(resp.context["form"], "email", "This field is required.")

    def test_invalid_email(self):
        resp = self.post(email="not-an-email")
        self.assertFormError(resp.context["form"], "email", "Enter a valid email address.")

    def test_duplicate_email_case_insensitive(self):
        make_user("nena@example.com", "HELPER")
        resp = self.post(email="NENA@Example.com")
        self.assertIn("already exists", str(resp.context["form"].errors["email"]))
        self.assertEqual(User.objects.count(), 1)

    def test_password_mismatch(self):
        resp = self.post(password2="Different-123!")
        self.assertFormError(resp.context["form"], "password2", "The two passwords don't match.")

    def test_bad_contact_number(self):
        resp = self.post(contact_number="12345")
        self.assertIn("contact_number", resp.context["form"].errors)


class LoginLogoutTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com", "OWNER")

    def test_login_redirects_to_role_dashboard(self):
        resp = self.client.post(reverse("accounts:login"),
                                {"username": "OWNER@example.com", "password": PASSWORD}, follow=True)
        self.assertRedirects(resp, reverse("accounts:owner_dashboard"))

    def test_invalid_credentials_show_error(self):
        resp = self.client.post(reverse("accounts:login"), {"username": "owner@example.com", "password": "wrong"})
        self.assertContains(resp, "Incorrect email or password")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_ends_session(self):
        self.client.force_login(self.owner)
        resp = self.client.post(reverse("accounts:logout"), follow=True)
        self.assertRedirects(resp, reverse("accounts:login"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_protected_pages_redirect_to_login(self):
        for name in ["dashboard", "owner_dashboard", "helper_dashboard", "profile", "profile_edit", "password_change"]:
            url = reverse(f"accounts:{name}")
            resp = self.client.get(url)
            self.assertRedirects(resp, f"{reverse('accounts:login')}?next={url}", msg_prefix=name)


class RoleDashboardTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com", "OWNER")
        self.helper = make_user("helper@example.com", "HELPER")

    def test_helper_lands_on_helper_dashboard(self):
        self.client.force_login(self.helper)
        resp = self.client.get(reverse("accounts:dashboard"), follow=True)
        self.assertRedirects(resp, reverse("accounts:helper_dashboard"))
        self.assertContains(resp, "Record a sale")

    def test_helper_cannot_open_owner_dashboard(self):
        self.client.force_login(self.helper)
        resp = self.client.get(reverse("accounts:owner_dashboard"))
        self.assertEqual(resp.status_code, 403)
        self.assertContains(resp, "open this page", status_code=403)

    def test_owner_cannot_open_helper_dashboard(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("accounts:helper_dashboard")).status_code, 403)

    def test_owner_sees_owner_navigation(self):
        self.client.force_login(self.owner)
        resp = self.client.get(reverse("accounts:owner_dashboard"))
        self.assertContains(resp, "Reports")
        self.assertContains(resp, "Set up your store")


class ProfileTests(TestCase):
    def setUp(self):
        self.user = make_user("joy@example.com", "HELPER", name="Joy Reyes")
        self.other = make_user("ben@example.com", "HELPER", name="Ben Santos")
        self.client.force_login(self.user)

    def test_view_own_profile(self):
        resp = self.client.get(reverse("accounts:profile"))
        self.assertContains(resp, "joy@example.com")
        self.assertNotContains(resp, "ben@example.com")

    def test_update_profile(self):
        resp = self.client.post(reverse("accounts:profile_edit"),
                                {"full_name": "Joy  Reyes-Lim", "email": "joy.lim@example.com",
                                 "contact_number": "+639171234567"}, follow=True)
        self.assertRedirects(resp, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.full_name, "Joy Reyes-Lim")
        self.assertEqual(self.user.email, "joy.lim@example.com")
        self.assertContains(resp, "Profile saved.")

    def test_cannot_take_another_users_email(self):
        resp = self.client.post(reverse("accounts:profile_edit"),
                                {"full_name": "Joy", "email": "BEN@example.com", "contact_number": ""})
        self.assertIn("email", resp.context["form"].errors)

    def test_cannot_change_own_role(self):
        self.client.post(reverse("accounts:profile_edit"),
                         {"full_name": "Joy", "email": "joy@example.com", "role": "OWNER"})
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, "HELPER")

    def test_change_password_keeps_session(self):
        resp = self.client.post(reverse("accounts:password_change"),
                                {"old_password": PASSWORD, "new_password1": "Bagong-Pass-99",
                                 "new_password2": "Bagong-Pass-99"}, follow=True)
        self.assertRedirects(resp, reverse("accounts:profile"))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Bagong-Pass-99"))


class RoleConstraintTests(TestCase):
    def test_database_rejects_unknown_role(self):
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            User.objects.create_user(email="x@example.com", password=PASSWORD, full_name="X", role="ADMIN")
