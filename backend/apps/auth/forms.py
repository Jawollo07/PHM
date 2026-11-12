from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

User = get_user_model()


class RegistrationForm(forms.Form):
    username = forms.CharField(max_length=150, strip=True, label="Benutzername")
    email = forms.EmailField(max_length=254, label="E-Mail-Adresse")
    password1 = forms.CharField(
        label="Passwort",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    password2 = forms.CharField(
        label="Passwort wiederholen",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Dieser Benutzername ist bereits vergeben.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Diese E-Mail-Adresse wird bereits verwendet.")
        return email

    def clean(self):
        cleaned = super().clean()
        password1 = cleaned.get("password1")
        password2 = cleaned.get("password2")
        if password1 and password2 and password1 != password2:
            self.add_error("password2", "Die Passwörter stimmen nicht überein.")
        if password1:
            candidate = User(
                username=cleaned.get("username", ""),
                email=cleaned.get("email", ""),
            )
            try:
                validate_password(password1, user=candidate)
            except ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self):
        if not self.is_valid():
            raise ValueError("RegistrationForm must be valid before saving.")
        return User.objects.create_user(
            username=self.cleaned_data["username"],
            email=self.cleaned_data["email"],
            password=self.cleaned_data["password1"],
        )
