import os
import secrets

# Isolated test runs use an ephemeral non-production signing key unless one is supplied explicitly.
os.environ.setdefault("DJANGO_SECRET_KEY", secrets.token_urlsafe(64))

from .settings import *  # noqa: F403

DATABASES = {  # noqa: F405
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
