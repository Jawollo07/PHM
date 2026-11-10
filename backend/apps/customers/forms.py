from django import forms
from django.contrib.auth import get_user_model


class AccountDetailsForm(forms.Form):
    username = forms.CharField(label="Benutzername", max_length=150)
    email = forms.EmailField(label="E-Mail-Adresse", max_length=254)
    phone_number = forms.CharField(
        label="Telefonnummer",
        max_length=30,
        required=False,
    )

    recipient_name = forms.CharField(label="Empfängername", max_length=255, required=False)
    company_name = forms.CharField(label="Unternehmen", max_length=255, required=False)
    street = forms.CharField(label="Straße", max_length=255, required=False)
    house_number = forms.CharField(label="Hausnummer", max_length=30, required=False)
    address_line_2 = forms.CharField(label="Adresszusatz", max_length=255, required=False)
    postal_code = forms.CharField(label="Postleitzahl", max_length=20, required=False)
    city = forms.CharField(label="Stadt", max_length=120, required=False)
    state = forms.CharField(label="Bundesland", max_length=120, required=False)
    country = forms.CharField(label="Land", max_length=64, required=False)

    language = forms.ChoiceField(
        label="Sprache",
        choices=(("de", "Deutsch"), ("en", "Englisch")),
    )
    email_notifications = forms.BooleanField(label="E-Mail", required=False)
    service_notifications = forms.BooleanField(label="Service", required=False)
    payment_notifications = forms.BooleanField(label="Zahlungen", required=False)
    security_notifications = forms.BooleanField(label="Sicherheit", required=False)
    marketing_emails = forms.BooleanField(label="Marketing-E-Mails", required=False)

    address_required_fields = ("recipient_name", "street", "postal_code", "city")
    address_fields = (
        "recipient_name",
        "company_name",
        "street",
        "house_number",
        "address_line_2",
        "postal_code",
        "city",
        "state",
    )

    def __init__(
        self,
        *args,
        user,
        customer=None,
        address=None,
        customer_settings=None,
        **kwargs,
    ):
        self.user = user
        self.address_exists = address is not None
        initial = {
            "username": user.username,
            "email": user.email,
            "phone_number": customer.phone_number if customer else "",
            "language": customer_settings.language if customer_settings else "de",
            "email_notifications": (
                customer_settings.email_notifications if customer_settings else True
            ),
            "service_notifications": (
                customer_settings.service_notifications if customer_settings else True
            ),
            "payment_notifications": (
                customer_settings.payment_notifications if customer_settings else True
            ),
            "security_notifications": (
                customer_settings.security_notifications if customer_settings else True
            ),
            "marketing_emails": customer_settings.marketing_emails if customer_settings else False,
        }
        if address:
            initial.update(
                {
                    field: getattr(address, field)
                    for field in self.address_fields
                }
            )
            initial["country"] = address.country
        else:
            initial["country"] = "Germany"
        initial.update(kwargs.pop("initial", {}))
        super().__init__(*args, initial=initial, **kwargs)

        current_language = initial["language"]
        if current_language not in dict(self.fields["language"].choices):
            self.fields["language"].choices = (
                *self.fields["language"].choices,
                (current_language, current_language),
            )

        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-checkbox" if isinstance(field, forms.BooleanField) else "form-input"
            )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if not username:
            raise forms.ValidationError("Der Benutzername darf nicht leer sein.")
        user_model = get_user_model()
        if user_model.objects.filter(username__iexact=username).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("Dieser Benutzername ist bereits vergeben.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        user_model = get_user_model()
        if user_model.objects.filter(email__iexact=email).exclude(pk=self.user.pk).exists():
            raise forms.ValidationError("Diese E-Mail-Adresse wird bereits verwendet.")
        return email

    def clean(self):
        cleaned_data = super().clean()
        has_address_details = any(
            cleaned_data.get(field)
            for field in self.address_fields
        )
        if self.address_exists or has_address_details:
            for field in self.address_required_fields:
                if not cleaned_data.get(field):
                    self.add_error(field, "Dieses Feld ist für eine Adresse erforderlich.")
        return cleaned_data
