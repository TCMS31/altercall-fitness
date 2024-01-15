"""The demo seed command used by compose and the README walkthrough."""

from __future__ import annotations

from io import StringIO

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, override_settings

from accounts.management.commands.seed_demo import DEMO_MEMBERS
from accounts.providers import get_identity_provider, reset_cache


@override_settings(AUTH_PROVIDER="memory", AI_GOAL_PARSER="rules")
class SeedDemoTests(SimpleTestCase):
    def setUp(self) -> None:
        reset_cache()
        self.addCleanup(reset_cache)

    def seed(self, *args) -> str:
        out = StringIO()
        call_command("seed_demo", *args, stdout=out)
        return out.getvalue()

    def test_seeds_every_member_confirmed_with_a_parsed_goal(self):
        self.seed()
        provider = get_identity_provider()
        for member in DEMO_MEMBERS:
            profile = provider.get_user(username=member["username"])
            self.assertTrue(profile.confirmed)
            self.assertIn("goal_type", profile.attributes)

    def test_running_twice_skips_existing_members(self):
        self.seed()
        first_id = get_identity_provider().get_user(username="yuki.tanaka").subject_id
        output = self.seed()
        self.assertIn("already present", output)
        self.assertEqual(
            get_identity_provider().get_user(username="yuki.tanaka").subject_id, first_id
        )

    def test_unconfirmed_flag_leaves_the_last_member_awaiting_otp(self):
        self.seed("--unconfirmed")
        last = DEMO_MEMBERS[-1]["username"]
        self.assertFalse(get_identity_provider().get_user(username=last).confirmed)

    @override_settings(AUTH_PROVIDER="cognito")
    def test_refuses_to_seed_a_real_directory(self):
        with self.assertRaises(CommandError):
            self.seed()
