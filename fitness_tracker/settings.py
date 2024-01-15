"""Django settings for the AlterCall fitness identity service.

Everything environment-specific is read from the environment with an explicit
default and an explicit type. Nothing secret is hard-coded: the previous
version shipped a literal ``SECRET_KEY`` and a production EC2 host in this
file, both of which are now env-driven.
"""

from __future__ import annotations

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load the project's own .env explicitly. A bare load_dotenv() searches upward
# from the *current working directory*, so running manage.py from anywhere but
# the repo root silently picked up no configuration at all.
load_dotenv(BASE_DIR / ".env")


def env_str(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    return value.strip() if isinstance(value, str) else value


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer, got {raw!r}") from exc


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default) or ""
    return [item.strip() for item in raw.split(",") if item.strip()]


# --------------------------------------------------------------------- core

DEBUG = env_bool("DJANGO_DEBUG", default=False)

#: Development fallback only. Running with DEBUG off and no DJANGO_SECRET_KEY
#: is a configuration error, not something to paper over with a default.
_DEV_SECRET_KEY = "django-insecure-development-only-do-not-use-in-production"
SECRET_KEY = env_str("DJANGO_SECRET_KEY") or ""
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = _DEV_SECRET_KEY
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off. "
            "Generate one with: python -c "
            "'from django.core.management.utils import get_random_secret_key as g; print(g())'"
        )

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

ROOT_URLCONF = "fitness_tracker.urls"
WSGI_APPLICATION = "fitness_tracker.wsgi.application"
ASGI_APPLICATION = "fitness_tracker.asgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "graphene_django",
    "corsheaders",
    "accounts",
]

#: The Django admin has no models to manage here — this service keeps no user
#: state of its own — so it stays unmounted unless explicitly enabled.
ENABLE_DJANGO_ADMIN = env_bool("ENABLE_DJANGO_ADMIN", default=False)
if ENABLE_DJANGO_ADMIN:
    INSTALLED_APPS = [
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.sessions",
        "django.contrib.messages",
        *INSTALLED_APPS,
    ]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # CorsMiddleware must sit above CommonMiddleware: a redirect generated
    # there short-circuits the response, and anything registered below never
    # runs, so the CORS headers were silently dropped on those responses.
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]
if ENABLE_DJANGO_ADMIN:
    MIDDLEWARE += [
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
    ]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ]
            + (
                [
                    "django.contrib.auth.context_processors.auth",
                    "django.contrib.messages.context_processors.messages",
                ]
                if ENABLE_DJANGO_ADMIN
                else []
            ),
        },
    },
]

# The service is stateless: identity lives in the configured provider, not
# here. SQLite exists only so Django's own machinery has somewhere to point.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": env_str("DJANGO_DB_PATH") or (BASE_DIR / "db.sqlite3"),
    }
}

CACHES = {
    "default": {
        "BACKEND": env_str(
            "DJANGO_CACHE_BACKEND",
            "django.core.cache.backends.locmem.LocMemCache",
        ),
        "LOCATION": env_str("DJANGO_CACHE_LOCATION", "accounts-profiles"),
        "TIMEOUT": env_int("PROFILE_CACHE_TTL", 60),
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# ---------------------------------------------------------------------- CORS

CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
# Allowing every origin is a development convenience. In production an explicit
# allowlist is required; a blank list means "no browser origin permitted".
CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL_ORIGINS", default=DEBUG)

# ------------------------------------------------------------------ identity

AUTH_PROVIDER = (env_str("AUTH_PROVIDER", "cognito") or "cognito").lower()

COGNITO_REGION = env_str("COGNITO_REGION")
COGNITO_USER_POOL_ID = env_str("COGNITO_USER_POOL_ID")
COGNITO_CLIENT_ID = env_str("COGNITO_CLIENT_ID")
#: Override the Cognito endpoint — used by the benchmark harness and by
#: LocalStack-style test doubles. Never set in production.
COGNITO_ENDPOINT_URL = env_str("COGNITO_ENDPOINT_URL")

# Prefer the instance role in production; these exist for local development.
AWS_ACCESS_KEY_ID = env_str("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = env_str("AWS_SECRET_ACCESS_KEY")

PROFILE_CACHE_TTL = env_int("PROFILE_CACHE_TTL", 60)

# ------------------------------------------------------------------------ AI

AI_GOAL_PARSER = (env_str("AI_GOAL_PARSER", "rules") or "rules").lower()
AI_MODEL = env_str("AI_MODEL", "claude-opus-5")
ANTHROPIC_API_KEY = env_str("ANTHROPIC_API_KEY")

# ------------------------------------------------------------------- GraphQL

GRAPHENE = {"SCHEMA": "fitness_tracker.schema.schema"}
#: GraphiQL is the service's only UI. On by default in DEBUG, opt-in otherwise.
GRAPHIQL_ENABLED = env_bool("GRAPHIQL_ENABLED", default=DEBUG)

#: Seed demo members into the in-memory provider at startup (memory provider only).
SEED_DEMO_ON_START = env_bool("SEED_DEMO_ON_START", default=False)

# -------------------------------------------------------------------- security

if not DEBUG:
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 31536000)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# -------------------------------------------------------------------- logging

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)-8s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": env_str("LOG_LEVEL", "INFO")},
    "loggers": {
        "accounts": {"level": env_str("LOG_LEVEL", "INFO"), "propagate": True},
        "django.request": {"level": env_str("LOG_LEVEL", "INFO"), "propagate": True},
        # botocore logs every signed request at DEBUG, including headers.
        "botocore": {"level": "WARNING", "propagate": True},
    },
}
