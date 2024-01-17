from __future__ import annotations

import logging

from django.apps import AppConfig
from django.conf import settings

logger = logging.getLogger(__name__)


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"

    def ready(self) -> None:
        """Optionally seed the in-memory provider inside the server process.

        ``manage.py seed_demo`` writes into its own process, which a running
        dev server cannot see. Setting ``SEED_DEMO_ON_START=1`` (only honoured
        with ``AUTH_PROVIDER=memory``) populates the directory in-process so a
        freshly started server already has members to query.
        """
        from django.core.management import call_command

        if not settings.SEED_DEMO_ON_START:
            return
        if settings.AUTH_PROVIDER != "memory":
            logger.warning("SEED_DEMO_ON_START ignored: AUTH_PROVIDER is not 'memory'")
            return
        try:
            call_command("seed_demo", verbosity=0)
            logger.info("Seeded demo members into the in-memory identity provider")
        except Exception:
            logger.warning("Demo seeding failed", exc_info=True)
