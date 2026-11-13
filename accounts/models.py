from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q


class UserManager(BaseUserManager):
    """Manager for a user model that logs in with email instead of a username."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)  # stores a hash, never the plain password
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", User.Role.HELPER)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.OWNER)
        if extra_fields.get("is_staff") is not True or extra_fields.get("is_superuser") is not True:
            raise ValueError("A superuser needs is_staff=True and is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


ph_mobile_validator = RegexValidator(
    regex=r"^(09|\+639)\d{9}$",
    message="Enter a Philippine mobile number like 09171234567 or +639171234567.",
)


def profile_photo_path(instance, filename):
    return f"profile_photos/user_{instance.pk or 'new'}/{filename}"


class User(AbstractUser):
    """The `users` table from the SDD (F-01, BR-01, BR-02)."""

    class Role(models.TextChoices):
        OWNER = "OWNER", "Store owner"
        HELPER = "HELPER", "Store helper"

    # Log in with email; drop the username and first/last name columns.
    username = None
    first_name = None
    last_name = None

    email = models.EmailField("email address", max_length=100, unique=True,
                              error_messages={"unique": "An account with this email already exists."})
    full_name = models.CharField(max_length=100)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.HELPER)
    contact_number = models.CharField(max_length=13, blank=True, validators=[ph_mobile_validator])
    profile_photo = models.ImageField(upload_to=profile_photo_path, blank=True)
    # AbstractUser already has is_active; date_joined is the SDD's created_at.
    date_joined = models.DateTimeField("created at", auto_now_add=True, db_column="created_at")

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    objects = UserManager()

    class Meta:
        db_table = "users"
        constraints = [
            models.CheckConstraint(condition=Q(role__in=["OWNER", "HELPER"]), name="users_role_valid"),
        ]

    def __str__(self):
        return f"{self.full_name} <{self.email}>"

    def save(self, *args, **kwargs):
        if self.email:
            self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    @property
    def is_owner(self):
        return self.role == self.Role.OWNER

    @property
    def is_helper(self):
        return self.role == self.Role.HELPER

    @property
    def first_name_display(self):
        return self.full_name.split()[0] if self.full_name else self.email

    @property
    def initials(self):
        parts = self.full_name.split()
        return "".join(p[0] for p in parts[:2]).upper() or self.email[:1].upper()

    def get_full_name(self):
        return self.full_name

    def get_short_name(self):
        return self.first_name_display
