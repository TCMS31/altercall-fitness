"""Identity provider registry.

``AUTH_PROVIDER`` selects the implementation at runtime. Registering a new
backend is a two-line change here plus one new module — no service, schema or
test file needs to know about it.
"""

from __future__ import annotations

from collections.abc import Callable

from django.conf import settings

from accounts.providers.base import IdentityProvider
from accounts.providers.cognito import CognitoIdentityProvider
from accounts.providers.memory import InMemoryIdentityProvider

ProviderFactory = Callable[[], IdentityProvider]

_REGISTRY: dict[str, ProviderFactory] = {}
_instances: dict[str, IdentityProvider] = {}


def register(name: str, factory: ProviderFactory) -> None:
    """Register a provider factory under ``name``."""
    _REGISTRY[name] = factory


def available() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))


def _build_cognito() -> IdentityProvider:
    return CognitoIdentityProvider(
        region=settings.COGNITO_REGION,
        user_pool_id=settings.COGNITO_USER_POOL_ID,
        client_id=settings.COGNITO_CLIENT_ID,
        access_key_id=settings.AWS_ACCESS_KEY_ID,
        secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        endpoint_url=settings.COGNITO_ENDPOINT_URL,
    )


register("cognito", _build_cognito)
register("memory", lambda: InMemoryIdentityProvider())


def get_identity_provider(name: str | None = None) -> IdentityProvider:
    """Return the configured provider, building it once per process."""
    key = name or settings.AUTH_PROVIDER
    if key not in _REGISTRY:
        raise ImproperlyConfiguredProvider(key, available())
    if key not in _instances:
        _instances[key] = _REGISTRY[key]()
    return _instances[key]


def reset_cache() -> None:
    """Drop memoised provider instances. Used by tests and by ``seed_demo``."""
    _instances.clear()


class ImproperlyConfiguredProvider(RuntimeError):
    def __init__(self, name: str, known: tuple[str, ...]) -> None:
        super().__init__(
            f"Unknown AUTH_PROVIDER {name!r}. Available providers: {', '.join(known)}."
        )


__all__ = [
    "CognitoIdentityProvider",
    "IdentityProvider",
    "ImproperlyConfiguredProvider",
    "InMemoryIdentityProvider",
    "available",
    "get_identity_provider",
    "register",
    "reset_cache",
]
