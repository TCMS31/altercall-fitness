"""Cognito adapter tests.

Every AWS call is served by ``botocore.stub.Stubber``: the real request shape
is validated against the service model, but nothing leaves the process and no
credentials are needed.
"""

from __future__ import annotations

import base64
import json

from botocore.stub import ANY, Stubber
from django.test import SimpleTestCase

from accounts import errors
from accounts.providers import CognitoIdentityProvider


def make_id_token(**claims) -> str:
    def segment(payload: dict) -> str:
        raw = json.dumps(payload).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{segment({'alg': 'RS256'})}.{segment(claims)}.signature"


class CognitoProviderTests(SimpleTestCase):
    def setUp(self) -> None:
        self.provider = CognitoIdentityProvider(
            region="eu-north-1",
            user_pool_id="eu-north-1_TESTPOOL",
            client_id="test-client-id",
            access_key_id="testing",
            secret_access_key="testing",
        )
        self.stub = Stubber(self.provider.client)
        self.stub.activate()
        self.addCleanup(self.stub.deactivate)

    # ------------------------------------------------------------- happy path

    def test_sign_up_sends_email_name_and_prefixed_custom_attributes(self):
        self.stub.add_response(
            "sign_up",
            {"UserConfirmed": False, "UserSub": "sub-123"},
            {
                "ClientId": "test-client-id",
                "Username": "ada",
                "Password": "Str0ng-Test-Pass!",
                "UserAttributes": [
                    {"Name": "email", "Value": "ada@example.com"},
                    {"Name": "name", "Value": "Ada"},
                    {"Name": "custom:goal_type", "Value": "endurance"},
                ],
            },
        )
        profile = self.provider.sign_up(
            username="ada",
            password="Str0ng-Test-Pass!",
            email="ada@example.com",
            name="Ada",
            attributes={"goal_type": "endurance"},
        )
        self.assertEqual(profile.subject_id, "sub-123")
        self.assertFalse(profile.confirmed)
        self.stub.assert_no_pending_responses()

    def test_sign_in_reads_the_profile_from_the_id_token_without_a_second_call(self):
        """The regression this guards: sign-in used to make two AWS calls.

        ``initiate_auth`` already returns an ID token containing sub, email and
        name, so the follow-up ``admin_get_user`` was pure latency and pure
        admin-API quota. Only one response is stubbed — if the provider made a
        second call, the stubber would raise.
        """
        id_token = make_id_token(
            sub="sub-123",
            email="ada@example.com",
            name="Ada Lovelace",
            **{"cognito:username": "ada", "custom:goal_type": "strength"},
        )
        self.stub.add_response(
            "initiate_auth",
            {
                "AuthenticationResult": {
                    "AccessToken": "access-token",
                    "RefreshToken": "refresh-token",
                    "IdToken": id_token,
                    "ExpiresIn": 3600,
                    "TokenType": "Bearer",
                }
            },
            {
                "ClientId": "test-client-id",
                "AuthFlow": "USER_PASSWORD_AUTH",
                "AuthParameters": ANY,
            },
        )
        session = self.provider.sign_in(username="ada", password="Str0ng-Test-Pass!")

        self.assertEqual(session.profile.subject_id, "sub-123")
        self.assertEqual(session.profile.email, "ada@example.com")
        self.assertEqual(session.profile.name, "Ada Lovelace")
        self.assertEqual(session.profile.attributes["goal_type"], "strength")
        self.assertEqual(session.tokens.expires_in, 3600)
        self.stub.assert_no_pending_responses()

    def test_sign_in_falls_back_to_a_lookup_when_the_id_token_is_unusable(self):
        self.stub.add_response(
            "initiate_auth",
            {"AuthenticationResult": {"AccessToken": "access", "IdToken": "not-a-jwt"}},
            {"ClientId": ANY, "AuthFlow": ANY, "AuthParameters": ANY},
        )
        self.stub.add_response(
            "admin_get_user",
            {
                "Username": "ada",
                "UserStatus": "CONFIRMED",
                "UserAttributes": [
                    {"Name": "sub", "Value": "sub-123"},
                    {"Name": "email", "Value": "ada@example.com"},
                ],
            },
            {"UserPoolId": "eu-north-1_TESTPOOL", "Username": "ada"},
        )
        session = self.provider.sign_in(username="ada", password="pw")
        self.assertEqual(session.profile.subject_id, "sub-123")
        self.stub.assert_no_pending_responses()

    def test_get_user_maps_attributes_and_confirmation_status(self):
        self.stub.add_response(
            "admin_get_user",
            {
                "Username": "ada",
                "UserStatus": "CONFIRMED",
                "UserAttributes": [
                    {"Name": "sub", "Value": "sub-123"},
                    {"Name": "email", "Value": "ada@example.com"},
                    {"Name": "name", "Value": "Ada"},
                    {"Name": "custom:goal_type", "Value": "fat_loss"},
                ],
            },
            {"UserPoolId": "eu-north-1_TESTPOOL", "Username": "ada"},
        )
        profile = self.provider.get_user(username="ada")
        self.assertTrue(profile.confirmed)
        self.assertEqual(profile.attributes, {"goal_type": "fat_loss"})

    # ---------------------------------------------------------- error mapping

    def test_client_errors_are_translated_to_domain_errors(self):
        cases = [
            ("UsernameExistsException", errors.UserAlreadyExists),
            ("InvalidPasswordException", errors.WeakPassword),
            ("TooManyRequestsException", errors.TooManyRequests),
        ]
        for aws_code, expected in cases:
            with self.subTest(aws_code=aws_code):
                self.stub.add_client_error("sign_up", service_error_code=aws_code)
                with self.assertRaises(expected):
                    self.provider.sign_up(
                        username="ada",
                        password="pw",
                        email="ada@example.com",
                        name="Ada",
                    )

    def test_unknown_user_on_sign_in_is_reported_as_invalid_credentials(self):
        """Never let the endpoint be used to enumerate accounts."""
        self.stub.add_client_error("initiate_auth", service_error_code="UserNotFoundException")
        with self.assertRaises(errors.InvalidCredentials):
            self.provider.sign_in(username="nobody", password="pw")

    def test_unmapped_aws_errors_do_not_leak_to_the_caller(self):
        self.stub.add_client_error(
            "admin_get_user",
            service_error_code="InternalErrorException",
            service_message="pool eu-north-1_REAL request id 1234",
        )
        with self.assertRaises(errors.ProviderUnavailable) as caught:
            self.provider.get_user(username="ada")
        self.assertNotIn("eu-north-1_REAL", str(caught.exception))


class CognitoConfigurationTests(SimpleTestCase):
    def test_missing_configuration_raises_provider_unavailable_not_no_region(self):
        """The original fatal bug: an unconfigured checkout 500'd on import.

        ``boto3.client`` was built at module import with ``region_name=None``,
        so ``botocore.NoRegionError`` escaped while Django was importing the
        schema — every GraphQL request, including introspection, returned 500.
        """
        provider = CognitoIdentityProvider(region=None, user_pool_id=None, client_id=None)
        with self.assertRaises(errors.ProviderUnavailable):
            provider.get_user(username="ada")
        self.assertFalse(provider.health())
