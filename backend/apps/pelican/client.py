import json
import secrets
import string
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings


class PelicanAPIError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class PelicanClient:
    """Small fail-closed client for the Pelican Application API."""

    def __init__(self):
        self.base_url = getattr(settings, "PELICAN_PANEL_URL", "").rstrip("/")
        self.token = getattr(settings, "PELICAN_APPLICATION_API_TOKEN", "")
        self.timeout = int(getattr(settings, "PELICAN_API_TIMEOUT", 10))
        if not self.base_url or not self.token:
            raise PelicanAPIError("not_configured")
        if not self.base_url.startswith("https://"):
            raise PelicanAPIError("https_required")

    def _request(self, method, path, payload=None):
        url = f"{self.base_url}/api/application/{path.lstrip('/')}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "Application/vnd.pterodactyl.v1+json",
            "Content-Type": "application/json",
        })
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read(2_000_000)
                return json.loads(body.decode("utf-8")) if body else {}
        except HTTPError as exc:
            # Never persist or expose response bodies: they may contain panel details.
            raise PelicanAPIError(f"http_{exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise PelicanAPIError("connection_error") from None
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise PelicanAPIError("invalid_response") from None

    def find_user_by_email(self, email):
        response = self._request("GET", f"users?{urlencode({'filter[email]': email, 'per_page': 100})}")
        matches = [
            row.get("attributes", {}) for row in response.get("data", [])
            if row.get("attributes", {}).get("email", "").casefold() == email.casefold()
        ]
        if len(matches) > 1:
            raise PelicanAPIError("duplicate_panel_email")
        return matches[0] if matches else None

    def create_user(self, *, email, username, first_name):
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
        password = "".join(secrets.choice(alphabet) for _ in range(48))
        response = self._request("POST", "users", {
            "email": email,
            "username": username[:191],
            "first_name": first_name[:191] or "Customer",
            "last_name": "PHM",
            "password": password,
        })
        return response.get("attributes", {})

    def ensure_user(self, *, email, username, first_name):
        existing = self.find_user_by_email(email)
        if existing:
            return existing, False
        created = self.create_user(email=email, username=username, first_name=first_name)
        if not created.get("id") or created.get("email", "").casefold() != email.casefold():
            raise PelicanAPIError("create_response_mismatch")
        return created, True
