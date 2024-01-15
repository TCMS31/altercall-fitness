"""Service-layer behaviour: caching, goal attachment, and call counts."""

from __future__ import annotations

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from accounts import errors
from accounts.services import AccountService
from accounts.tests.factories import PASSWORD, CountingProvider, StubGoalParser


class AccountServiceTests(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()
        self.addCleanup(cache.clear)
        self.provider = CountingProvider()
        self.parser = StubGoalParser()
        self.service = AccountService(provider=self.provider, goal_parser=self.parser, cache_ttl=60)

    def _register(self, username="ada", goal=None):
        return self.service.register(
            username=username,
            password=PASSWORD,
            email=f"{username}@example.com",
            name="Ada",
            goal=goal,
        )

    # ----------------------------------------------------------- registration

    def test_registration_without_a_goal_skips_the_parser(self):
        profile, goal = self._register()
        self.assertIsNone(goal)
        self.assertEqual(self.parser.seen, [])
        self.assertEqual(profile.attributes, {})

    def test_registration_attaches_structured_goal_attributes(self):
        profile, goal = self._register(goal="lose 5 kg in 3 months, 4x a week")
        self.assertEqual(self.parser.seen, ["lose 5 kg in 3 months, 4x a week"])
        self.assertEqual(goal.goal_type, "fat_loss")
        self.assertEqual(
            profile.attributes,
            {
                "goal_type": "fat_loss",
                "goal_target": "5 kg",
                "goal_timeframe": "3 months",
                "sessions_per_week": "4",
            },
        )

    def test_blank_required_fields_are_rejected_before_reaching_the_provider(self):
        with self.assertRaises(errors.IdentityError):
            self._register(username="   ")
        self.assertEqual(self.provider.calls, [])

    # ----------------------------------------------------------------- caching

    def test_repeated_lookups_hit_the_cache_not_the_directory(self):
        self._register()
        self.service.confirm(username="ada", code="123456")
        self.provider.calls.clear()

        for _ in range(25):
            self.service.find_user(username="ada")

        self.assertEqual(self.provider.count("get_user"), 0)

    def test_cache_is_bypassed_when_the_ttl_is_zero(self):
        self._register()
        self.service.confirm(username="ada", code="123456")
        service = AccountService(provider=self.provider, cache_ttl=0)
        cache.clear()
        self.provider.calls.clear()

        for _ in range(5):
            service.find_user(username="ada")

        self.assertEqual(self.provider.count("get_user"), 5)

    def test_sign_in_makes_one_directory_call_and_warms_the_cache(self):
        self._register()
        self.service.confirm(username="ada", code="123456")
        self.provider.calls.clear()

        session = self.service.authenticate(username="ada", password=PASSWORD)
        self.service.find_user(username="ada")

        self.assertEqual(self.provider.calls, ["sign_in"])
        self.assertEqual(self.provider.count("get_user"), 0)
        self.assertTrue(session.tokens.access_token)

    def test_confirmation_refreshes_the_cached_profile(self):
        self._register()
        self.assertFalse(self.service.provider.get_user(username="ada").confirmed)
        self.service.confirm(username="ada", code="123456")
        self.provider.calls.clear()
        self.assertTrue(self.service.find_user(username="ada").confirmed)
        self.assertEqual(self.provider.count("get_user"), 0)

    @override_settings(PROFILE_CACHE_TTL=0)
    def test_ttl_defaults_come_from_settings(self):
        service = AccountService(provider=self.provider)
        self.assertEqual(service._cache_ttl, 0)
