"""Populate the in-memory identity provider with realistic demo members.

Used for local exploration and for the README screenshots. It refuses to run
against a real directory: seeding fake members into a production Cognito pool
is not a mistake worth leaving available.
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.providers import InMemoryIdentityProvider, get_identity_provider
from accounts.services import AccountService

DEMO_MEMBERS = [
    {
        "username": "rhiannon.pike",
        "name": "Rhiannon Pike",
        "email": "rhiannon.pike@example.com",
        "password": "Str0ng-Demo-Pass!",
        "goal": "I want to lose 6 kg before my sister's wedding in June and I can train four times a week",
    },
    {
        "username": "marcus.adeyemi",
        "name": "Marcus Adeyemi",
        "email": "marcus.adeyemi@example.com",
        "password": "Str0ng-Demo-Pass!",
        "goal": "Add serious muscle over the next 6 months, lifting five days a week",
    },
    {
        "username": "yuki.tanaka",
        "name": "Yuki Tanaka",
        "email": "yuki.tanaka@example.com",
        "password": "Str0ng-Demo-Pass!",
        "goal": "Run a half marathon in 12 weeks, three sessions a week",
    },
    {
        "username": "dana.oconnell",
        "name": "Dana O'Connell",
        "email": "dana.oconnell@example.com",
        "password": "Str0ng-Demo-Pass!",
        "goal": "Get my deadlift stronger - 140 kg within 4 months, training four times a week",
    },
]


class Command(BaseCommand):
    help = "Seed the in-memory identity provider with demo members."

    def add_arguments(self, parser):
        parser.add_argument(
            "--unconfirmed",
            action="store_true",
            help="Leave the last member unconfirmed, to demo the OTP flow.",
        )

    def handle(self, *args, **options):
        verbose = options.get("verbosity", 1) >= 1
        provider = get_identity_provider()
        if not isinstance(provider, InMemoryIdentityProvider):
            raise CommandError(
                f"seed_demo only runs against the in-memory provider "
                f"(AUTH_PROVIDER is {settings.AUTH_PROVIDER!r}). "
                f"Re-run with AUTH_PROVIDER=memory."
            )

        service = AccountService(provider=provider)
        created = 0
        for index, member in enumerate(DEMO_MEMBERS):
            last = index == len(DEMO_MEMBERS) - 1
            confirmed = not (options["unconfirmed"] and last)
            profile, goal = service.register(**member)
            if confirmed:
                profile = service.confirm(username=profile.username, code="123456")
            created += 1
            if verbose:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {profile.username:<18} {goal.goal_type:<16}"
                        f" {'confirmed' if confirmed else 'awaiting OTP'}"
                    )
                )
        if verbose:
            self.stdout.write(f"Seeded {created} demo members via the {provider.name} provider.")
