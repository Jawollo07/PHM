from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.core.exceptions import ValidationError

from apps.pelican.client import PelicanAPIError
from apps.pelican.services import sync_pelican_password


class _PelicanPasswordSyncMixin:
    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        new_password = cleaned.get("new_password1")
        if new_password:
            try:
                sync_pelican_password(self.user, new_password)
            except PelicanAPIError:
                raise ValidationError(
                    "Das Pelican-Passwort konnte nicht aktualisiert werden. "
                    "Dein PHM-Passwort wurde nicht geändert. Bitte versuche es später erneut."
                )
        return cleaned


class SynchronizedPasswordChangeForm(_PelicanPasswordSyncMixin, PasswordChangeForm):
    pass


class SynchronizedSetPasswordForm(_PelicanPasswordSyncMixin, SetPasswordForm):
    pass
