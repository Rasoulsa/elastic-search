import os
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


def env_csv(name: str, default: str) -> list[str]:
    return [value.strip() for value in os.getenv(name, default).split(",") if value.strip()]


configured_secret_key = os.getenv("DJANGO_SECRET_KEY")
if not configured_secret_key or not configured_secret_key.strip():
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set to a non-empty value.")

SECRET_KEY = configured_secret_key
DEBUG = env_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env_csv("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "drf_spectacular",
    "apps.accounts",
    "apps.profiles",
    "apps.search",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("POSTGRES_DB", "profiles"),
        "USER": os.getenv("POSTGRES_USER", "profiles"),
        "PASSWORD": os.getenv("POSTGRES_PASSWORD", "profiles"),
        "HOST": os.getenv("POSTGRES_HOST", "localhost"),
        "PORT": os.getenv("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(os.getenv("POSTGRES_CONN_MAX_AGE", "60")),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "SIGNING_KEY": SECRET_KEY,
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
}

CORS_ALLOWED_ORIGINS = env_csv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
CORS_ALLOW_CREDENTIALS = False

SPECTACULAR_SETTINGS = {
    "TITLE": "LinkedIn Profile Search API",
    "DESCRIPTION": "Authentication and profile search API.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

ELASTICSEARCH_URL = os.getenv("ELASTICSEARCH_URL", "http://localhost:9200")
ELASTICSEARCH_REQUEST_TIMEOUT = float(os.getenv("ELASTICSEARCH_REQUEST_TIMEOUT", "10"))
ELASTICSEARCH_INDEX = os.getenv("ELASTICSEARCH_INDEX", "linkedin_profiles_v1")
