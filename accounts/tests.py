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
                "password1": PASSWORD, "password2": PASSWORD}
        data.update(overrides)
        return self.client.post(self.url, data, follow=True)

    def test_register_success_hashes_password(self):
        resp = self.post()
        self.assertRedirects(resp, reverse("accounts:login"))
        user = User.objects.get(email="nena@example.com")
        self.assertNotEqual(user.password, PASSWORD)
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
        self.assertTrue(user.check_password(PASSWORD))
        self.assertIn("account created", [str(m) for m in get_messages(resp.wsgi_request)][0])

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
        self.assertContains(resp, "Record a restock")

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
        self.assertContains(resp, "Products low on stock")


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


class RoleOnSignupTests(TestCase):
    """ISS-01: nobody can choose the owner role while registering."""

    url = reverse("accounts:register")

    def register(self, email, **extra):
        data = {"full_name": "New Person", "email": email, "password1": PASSWORD, "password2": PASSWORD}
        data.update(extra)
        return self.client.post(self.url, data, follow=True)

    def test_first_account_is_owner_then_helpers(self):
        self.register("first@example.com")
        self.register("second@example.com")
        self.assertEqual(User.objects.get(email="first@example.com").role, "OWNER")
        self.assertEqual(User.objects.get(email="second@example.com").role, "HELPER")

    def test_posting_a_role_is_ignored(self):
        make_user("owner@example.com", "OWNER")
        resp = self.register("sneaky@example.com", role="OWNER")
        self.assertContains(resp, "Helper account created")
        self.assertEqual(User.objects.get(email="sneaky@example.com").role, "HELPER")


class TeamTests(TestCase):
    def setUp(self):
        self.owner = make_user("owner@example.com", "OWNER", name="Nena Cruz")
        self.helper = make_user("helper@example.com", "HELPER", name="Joy Reyes")

    def test_owner_promotes_helper(self):
        self.client.force_login(self.owner)
        resp = self.client.post(reverse("accounts:team_change_role", args=[self.helper.pk]),
                                {"role": "OWNER"}, follow=True)
        self.assertContains(resp, "Joy Reyes is now a store owner.")
        self.helper.refresh_from_db()
        self.assertEqual(self.helper.role, "OWNER")

    def test_owner_cannot_demote_self(self):
        self.client.force_login(self.owner)
        resp = self.client.post(reverse("accounts:team_change_role", args=[self.owner.pk]),
                                {"role": "HELPER"}, follow=True)
        self.assertContains(resp, "can&#x27;t remove your own owner role")
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.role, "OWNER")

    def test_helper_cannot_change_roles(self):
        self.client.force_login(self.helper)
        self.assertEqual(self.client.get(reverse("accounts:team")).status_code, 403)
        resp = self.client.post(reverse("accounts:team_change_role", args=[self.helper.pk]), {"role": "OWNER"})
        self.assertEqual(resp.status_code, 403)
        self.helper.refresh_from_db()
        self.assertEqual(self.helper.role, "HELPER")

    def test_change_role_is_post_only_and_validates(self):
        self.client.force_login(self.owner)
        url = reverse("accounts:team_change_role", args=[self.helper.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        resp = self.client.post(url, {"role": "ADMIN"}, follow=True)
        self.assertContains(resp, "Choose a valid role.")
        self.assertEqual(self.client.post(reverse("accounts:team_change_role", args=[99999]),
                                          {"role": "OWNER"}).status_code, 404)


class ProfilePhotoTests(TestCase):
    """ISS-02: photos are validated and served by a login-protected view."""

    def setUp(self):
        import shutil, tempfile
        from django.test import override_settings
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = make_user("joy@example.com", "HELPER", name="Joy Reyes")
        self.client.force_login(self.user)

    def png(self, name="me.png"):
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        buf = io.BytesIO()
        Image.new("RGB", (20, 20), "green").save(buf, "PNG")
        return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")

    def upload(self, photo):
        return self.client.post(reverse("accounts:profile_edit"),
                                {"full_name": "Joy Reyes", "email": "joy@example.com", "contact_number": "",
                                 "profile_photo": photo}, follow=True)

    def test_upload_and_serve_only_when_logged_in(self):
        self.upload(self.png())
        self.user.refresh_from_db()
        url = self.user.profile_photo.url
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")
        self.client.logout()
        self.assertRedirects(self.client.get(url), f"{reverse('accounts:login')}?next={url}")

    def test_replacing_photo_deletes_old_file(self):
        import os
        with self.captureOnCommitCallbacks(execute=True):
            self.upload(self.png("first.png"))
        self.user.refresh_from_db()
        first = self.user.profile_photo.path
        with self.captureOnCommitCallbacks(execute=True):
            self.upload(self.png("second.png"))
        self.assertFalse(os.path.exists(first))

    def test_rejects_non_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        resp = self.upload(SimpleUploadedFile("evil.png", b"<script>alert(1)</script>", content_type="image/png"))
        self.assertIn("profile_photo", resp.context["form"].errors)

    def test_media_view_blocks_path_tricks(self):
        self.assertEqual(self.client.get("/media/../.env").status_code, 404)
        self.assertEqual(self.client.get("/media/missing.png").status_code, 404)

    def test_invalid_profile_edit_does_not_change_sidebar(self):
        make_user("ben@example.com", "HELPER")
        resp = self.client.post(reverse("accounts:profile_edit"),
                                {"full_name": "Joy Reyes", "email": "ben@example.com", "contact_number": ""})
        self.assertIn("email", resp.context["form"].errors)
        self.assertEqual(resp.context["user"].email, "joy@example.com")
