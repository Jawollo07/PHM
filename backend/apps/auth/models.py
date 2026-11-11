import uuid

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models, transaction
from django.utils import timezone


class UserManager(BaseUserManager):
    """Manager for username-based authentication and personal account provisioning."""

    use_in_migrations = True

    def create_user(self, username, email, password=None, **extra_fields):
        if not username or not username.strip():
            raise ValueError("A username is required.")
        if not email or not email.strip():
            raise ValueError("An email address is required.")

        username = username.strip()
        email = self.normalize_email(email.strip()).lower()
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)

        with transaction.atomic(using=self._db):
            user.save(using=self._db)
            # Import lazily to avoid a circular dependency between app models.
            from apps.customers.services import provision_personal_customer
            provision_personal_customer(user, using=self._db)

        return user

    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("email_verified", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(username, email, password, **extra_fields)


class User(AbstractUser):
    """Central PHM user identity."""

    username = models.CharField(max_length=150, unique=True, db_index=True)
    email = models.EmailField(unique=True, db_index=True)
    email_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS = ["email"]
    objects = UserManager()  # type: ignore

    class Meta:
        db_table = "accounts_user"
        ordering = ["-date_joined"]

    def __str__(self):
        return self.username


class UserProfile(models.Model):
    """Preferences that belong to the user identity, not the customer billing record."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=100, blank=True)
    timezone = models.CharField(max_length=64, default="Europe/Berlin")
    language = models.CharField(max_length=10, default="de")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_user_profile"

    def __str__(self):
        return f"Profile: {self.user.email}"


class EmailVerification(models.Model):
    """Email verification tokens. Only token hashes are stored."""

    class Purpose(models.TextChoices):
        REGISTRATION = "registration", "Registration"
        EMAIL_CHANGE = "email_change", "Email change"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_verifications")
    email = models.EmailField()
    token_hash = models.CharField(max_length=64, unique=True)
    purpose = models.CharField(max_length=20, choices=Purpose.choices, default=Purpose.REGISTRATION)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "accounts_email_verification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "purpose", "created_at"], name="email_ver_user_purpose_idx"),
        ]

    def __str__(self):
        return f"{self.purpose}: {self.email}"

    @property
    def is_valid(self):
        return self.verified_at is None and self.expires_at > timezone.now()
