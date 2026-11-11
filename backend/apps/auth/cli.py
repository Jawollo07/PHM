import argparse
import os
import sys
from getpass import getpass
from pathlib import Path


def _setup_django():
    backend_dir = str(Path(__file__).resolve().parents[2])
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

    import django

    django.setup()


def _create_user(args):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    from django.db import IntegrityError, transaction

    User = get_user_model()
    username = (args.username or input("Benutzername: ")).strip()
    email = (args.email or input("E-Mail-Adresse: ")).strip().lower()

    if not username or not email:
        print("Benutzername und E-Mail-Adresse dürfen nicht leer sein.", file=sys.stderr)
        return 2

    user = User(username=username, email=email)
    try:
        user.full_clean(exclude=["password"])
    except ValidationError as error:
        for field_errors in error.message_dict.values():
            for message in field_errors:
                print(message, file=sys.stderr)
        return 2

    password = getpass("Passwort: ")
    password_confirmation = getpass("Passwort wiederholen: ")
    if password != password_confirmation:
        print("Die Passwörter stimmen nicht überein.", file=sys.stderr)
        return 2

    try:
        validate_password(password, user=user)
    except ValidationError as error:
        for message in error.messages:
            print(message, file=sys.stderr)
        return 2

    try:
        with transaction.atomic():
            User.objects.create_user(
                username=username,
                email=email,
                password=password,
            )
    except IntegrityError:
        print("Benutzername oder E-Mail-Adresse ist bereits vergeben.", file=sys.stderr)
        return 2

    print(f"Benutzer '{username}' wurde erstellt.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="PHM-Benutzer verwalten.")
    commands = parser.add_subparsers(dest="command", required=True)

    create_user_parser = commands.add_parser(
        "create-user",
        help="Einen normalen Benutzer erstellen.",
    )
    create_user_parser.add_argument("--username", help="Benutzername")
    create_user_parser.add_argument("--email", help="E-Mail-Adresse")

    args = parser.parse_args(argv)
    _setup_django()

    if args.command == "create-user":
        return _create_user(args)

    parser.error(f"Unbekannter Befehl: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
