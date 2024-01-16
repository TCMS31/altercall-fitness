#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fitness_tracker.settings")

    # `manage.py test` must work on a fresh clone with no .env at all: the test
    # suite never touches AWS, so default it to the in-memory provider and a
    # throwaway secret rather than making a reviewer configure Cognito first.
    if "test" in sys.argv[1:2]:
        os.environ.setdefault("DJANGO_SECRET_KEY", "test-only-secret-key")
        os.environ.setdefault("AUTH_PROVIDER", "memory")
        os.environ.setdefault("AI_GOAL_PARSER", "rules")
        # Production redirects plain HTTP to HTTPS; the test client speaks HTTP.
        os.environ.setdefault("DJANGO_SECURE_SSL_REDIRECT", "0")
        # Expected-failure paths log loudly; keep the test report readable.
        os.environ.setdefault("LOG_LEVEL", "CRITICAL")

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
