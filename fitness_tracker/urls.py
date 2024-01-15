"""URL configuration.

``/graphql`` and ``/graphql/`` are both routed so a client or proxy that
normalises the trailing slash does not get a 404 from a healthy service.
"""

from __future__ import annotations

from django.conf import settings
from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from accounts.views import SettingsAwareGraphQLView, health

graphql_view = csrf_exempt(SettingsAwareGraphQLView.as_view())

urlpatterns = [
    path("graphql", graphql_view, name="graphql"),
    path("graphql/", graphql_view, name="graphql-slash"),
    path("healthz", health, name="health"),
]

if settings.ENABLE_DJANGO_ADMIN:
    from django.contrib import admin

    urlpatterns.append(path("admin/", admin.site.urls))
