"""Plain HTTP views. The GraphQL endpoint lives in :mod:`accounts.schema`."""

from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from graphene_django.views import GraphQLView

from accounts.providers import get_identity_provider


class SettingsAwareGraphQLView(GraphQLView):
    """A GraphQL view that reads ``GRAPHIQL_ENABLED`` per request.

    ``GraphQLView.as_view(graphiql=...)`` freezes the flag at import time, so
    the in-browser IDE could not be toggled by configuration without editing
    the URLconf. Django builds a fresh view instance per request, so setting
    the attribute in ``dispatch`` is safe.
    """

    def dispatch(self, request, *args, **kwargs):
        self.graphiql = settings.GRAPHIQL_ENABLED
        return super().dispatch(request, *args, **kwargs)


def health(request: HttpRequest) -> JsonResponse:
    """Readiness probe used by the container healthcheck and by load balancers.

    Reports 503 when the selected identity provider is not configured, so a
    misconfigured deployment fails fast instead of serving 500s per request.
    """
    try:
        provider = get_identity_provider()
        ready = provider.health()
        name = provider.name
    except Exception:  # noqa: BLE001 - the probe must never raise
        ready, name = False, settings.AUTH_PROVIDER
    return JsonResponse(
        {"status": "ok" if ready else "degraded", "provider": name},
        status=200 if ready else 503,
    )
