"""The provider registry is the project's main extension point."""

from __future__ import annotations

from django.test import SimpleTestCase, override_settings

from accounts.domain import AuthSession, AuthTokens, UserProfile
from accounts.providers import (
    CognitoIdentityProvider,
    IdentityProvider,
    ImproperlyConfiguredProvider,
    InMemoryIdentityProvider,
    available,
    get_identity_provider,
    register,
    reset_cache,
)


class NullProvider(IdentityProvider):
    """A third provider, added by a test, to prove the seam is real."""

    name = "null"

    def sign_up(self, **kwargs):
        return UserProfile(username=kwargs["username"])

    def confirm_sign_up(self, **kwargs):
        return UserProfile(username=kwargs["username"], confirmed=True)

    def sign_in(self, **kwargs):
        return AuthSession(
            profile=UserProfile(username=kwargs["username"]),
            tokens=AuthTokens(access_token="null-token"),
        )

    def get_user(self, **kwargs):
        return UserProfile(username=kwargs["username"])


class RegistryTests(SimpleTestCase):
    def setUp(self) -> None:
        reset_cache()
        self.addCleanup(reset_cache)

    def test_builtin_providers_are_registered(self):
        self.assertIn("cognito", available())
        self.assertIn("memory", available())

    @override_settings(AUTH_PROVIDER="memory")
    def test_setting_selects_the_implementation(self):
        self.assertIsInstance(get_identity_provider(), InMemoryIdentityProvider)

    @override_settings(AUTH_PROVIDER="cognito")
    def test_cognito_is_selected_without_being_constructed_eagerly(self):
        provider = get_identity_provider()
        self.assertIsInstance(provider, CognitoIdentityProvider)

    @override_settings(AUTH_PROVIDER="memory")
    def test_the_provider_is_built_once_per_process(self):
        self.assertIs(get_identity_provider(), get_identity_provider())

    @override_settings(AUTH_PROVIDER="does-not-exist")
    def test_an_unknown_provider_name_fails_loudly(self):
        with self.assertRaises(ImproperlyConfiguredProvider):
            get_identity_provider()

    def test_a_third_party_provider_can_be_registered(self):
        register("null", NullProvider)
        with override_settings(AUTH_PROVIDER="null"):
            provider = get_identity_provider()
        self.assertIsInstance(provider, NullProvider)
        self.assertIn("null", available())
