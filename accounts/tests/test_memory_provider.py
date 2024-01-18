"""The in-memory provider must honour exactly the same contract as Cognito."""

from __future__ import annotations

from django.test import SimpleTestCase

from accounts import errors
from accounts.providers import InMemoryIdentityProvider
from accounts.providers.memory import DEFAULT_CONFIRMATION_CODE
from accounts.tests.factories import PASSWORD, make_member


class InMemoryProviderTests(SimpleTestCase):
    def setUp(self) -> None:
        self.provider = InMemoryIdentityProvider()

    def test_sign_up_returns_unconfirmed_profile_with_subject_id(self):
        profile = self.provider.sign_up(
            username="ada", password=PASSWORD, email="ada@example.com", name="Ada"
        )
        self.assertEqual(profile.username, "ada")
        self.assertEqual(profile.email, "ada@example.com")
        self.assertFalse(profile.confirmed)
        self.assertTrue(profile.subject_id)

    def test_duplicate_sign_up_is_rejected(self):
        make_member(self.provider, "ada")
        with self.assertRaises(errors.UserAlreadyExists):
            self.provider.sign_up(
                username="ada", password=PASSWORD, email="x@example.com", name="X"
            )

    def test_short_password_is_rejected(self):
        with self.assertRaises(errors.WeakPassword):
            self.provider.sign_up(
                username="ada", password="short", email="a@example.com", name="Ada"
            )

    def test_unconfirmed_user_cannot_sign_in(self):
        make_member(self.provider, "ada", confirmed=False)
        with self.assertRaises(errors.UserNotConfirmed):
            self.provider.sign_in(username="ada", password=PASSWORD)

    def test_wrong_confirmation_code_is_rejected(self):
        make_member(self.provider, "ada", confirmed=False)
        with self.assertRaises(errors.InvalidConfirmationCode):
            self.provider.confirm_sign_up(username="ada", code="000000")

    def test_confirmation_flips_the_flag_and_enables_sign_in(self):
        make_member(self.provider, "ada", confirmed=False)
        profile = self.provider.confirm_sign_up(username="ada", code=DEFAULT_CONFIRMATION_CODE)
        self.assertTrue(profile.confirmed)
        session = self.provider.sign_in(username="ada", password=PASSWORD)
        self.assertTrue(session.tokens.access_token)
        self.assertEqual(session.tokens.expires_in, 3600)

    def test_unknown_user_and_bad_password_are_indistinguishable(self):
        make_member(self.provider, "ada")
        with self.assertRaises(errors.InvalidCredentials) as unknown:
            self.provider.sign_in(username="nobody", password=PASSWORD)
        with self.assertRaises(errors.InvalidCredentials) as wrong:
            self.provider.sign_in(username="ada", password="Wr0ng-Pass!!")
        self.assertEqual(str(unknown.exception), str(wrong.exception))

    def test_password_is_not_stored_in_plain_text(self):
        make_member(self.provider, "ada")
        record = self.provider._users["ada"]
        self.assertNotIn(PASSWORD.encode(), record.password_hash)
        self.assertEqual(len(record.salt), 16)

    def test_get_user_raises_for_unknown_username(self):
        with self.assertRaises(errors.UserNotFound):
            self.provider.get_user(username="nobody")

    def test_custom_attributes_round_trip(self):
        profile = make_member(self.provider, "ada", attributes={"goal_type": "endurance"})
        self.assertEqual(profile.attributes["goal_type"], "endurance")
