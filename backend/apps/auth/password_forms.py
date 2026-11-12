from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.core.exceptions import ValidationError

from apps.pelican.client import PelicanAPIError
from apps.pelican.services import sync_pelican_password


class SynchronizedPasswordChangeForm(PasswordChangeForm):
    def save(self, commit=True):
        user = self.user
        new_password = self.cleaned_data["new_password1"]
        try:
            sync_pelican_password(user, new_password)
        except PelicanAPIError:
            raise ValidationError(
                "Das Pelican-Passwort konnte nicht aktualisiert werden. "
                "Dein PHM-Passwort wurde nicht geändert. Bitte versuche es später erneut."
            )
        return super().save(commit=commit)


class SynchronizedSetPasswordForm(SetPasswordForm):
    def save(self, commit=True):
        user = self.user
        new_password = self.cleaned_data["new_password1"]
        try:
            sync_pelican_password(user, new_password)
        except PelicanAPIError:
            raise ValidationError(
                "Das Pelican-Passwort konnte nicht aktualisiert werden. "
                "Dein PHM-Passwort wurde nicht geändert. Bitte versuche es später erneut."
            )
        return super().save(commit=commit)
