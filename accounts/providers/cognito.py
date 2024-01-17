"""AWS Cognito implementation of :class:`~accounts.providers.base.IdentityProvider`."""

from __future__ import annotations

import base64
import binascii
import json
import logging
from functools import cached_property
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from accounts import errors
from accounts.domain import AuthSession, AuthTokens, UserProfile
from accounts.providers.base import IdentityProvider

logger = logging.getLogger(__name__)

#: Cognito error code -> domain error. Anything unlisted becomes ProviderUnavailable.
_ERROR_MAP: dict[str, type[errors.IdentityError]] = {
    "UsernameExistsException": errors.UserAlreadyExists,
    "InvalidPasswordException": errors.WeakPassword,
    "InvalidParameterException": errors.WeakPassword,
    "NotAuthorizedException": errors.InvalidCredentials,
    "UserNotFoundException": errors.UserNotFound,
    "UserNotConfirmedException": errors.UserNotConfirmed,
    "CodeMismatchException": errors.InvalidConfirmationCode,
    "ExpiredCodeException": errors.InvalidConfirmationCode,
    "TooManyRequestsException": errors.TooManyRequests,
    "TooManyFailedAttemptsException": errors.TooManyRequests,
    "LimitExceededException": errors.TooManyRequests,
}


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    """Read the claims out of a JWT **without** verifying its signature.

    This is only ever applied to an ID token that Cognito just handed us over
    TLS inside the same API response, so there is no untrusted-input step to
    guard: we are reading a value we already trust the transport for. A token
    arriving from a *client* must be verified against the pool's JWKS instead —
    do not reuse this helper for that.
    """
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError, binascii.Error, UnicodeDecodeError):
        logger.warning("Could not decode ID token claims; falling back to a directory lookup")
        return {}


class CognitoIdentityProvider(IdentityProvider):
    """Talks to an AWS Cognito user pool.

    The boto3 client is built lazily on first use. Building it eagerly at import
    time meant that a checkout with no AWS configuration raised
    ``botocore.NoRegionError`` while Django was importing the schema module,
    turning every GraphQL request — including introspection — into a hard 500.
    """

    name = "cognito"

    def __init__(
        self,
        *,
        region: str | None,
        user_pool_id: str | None,
        client_id: str | None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self.region = region
        self.user_pool_id = user_pool_id
        self.client_id = client_id
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._endpoint_url = endpoint_url

    # ------------------------------------------------------------------ setup

    @cached_property
    def client(self):  # pragma: no cover - exercised indirectly via the stubber
        if not (self.region and self.user_pool_id and self.client_id):
            raise errors.ProviderUnavailable(
                "Cognito is selected but COGNITO_REGION, COGNITO_USER_POOL_ID and "
                "COGNITO_CLIENT_ID are not all set. Set them, or run with "
                "AUTH_PROVIDER=memory for local development."
            )
        kwargs: dict[str, Any] = {
            "region_name": self.region,
            "config": Config(retries={"max_attempts": 3, "mode": "standard"}),
        }
        # Omit explicit credentials so boto3 can fall back to the instance role
        # or the shared credential file, which is what production should use.
        if self._access_key_id and self._secret_access_key:
            kwargs["aws_access_key_id"] = self._access_key_id
            kwargs["aws_secret_access_key"] = self._secret_access_key
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        return boto3.client("cognito-idp", **kwargs)

    def health(self) -> bool:
        return bool(self.region and self.user_pool_id and self.client_id)

    # ------------------------------------------------------------- translation

    @staticmethod
    def _translate(exc: ClientError) -> errors.IdentityError:
        code = exc.response.get("Error", {}).get("Code", "")
        domain_error = _ERROR_MAP.get(code)
        if domain_error is not None:
            return domain_error()
        logger.error("Unmapped Cognito error %s: %s", code, exc, exc_info=True)
        return errors.ProviderUnavailable()

    # ----------------------------------------------------------------- queries

    def sign_up(
        self,
        *,
        username: str,
        password: str,
        email: str,
        name: str,
        attributes: dict[str, str] | None = None,
    ) -> UserProfile:
        user_attributes = [
            {"Name": "email", "Value": email},
            {"Name": "name", "Value": name},
        ]
        # Custom attributes must already exist in the pool schema; see the
        # README's Limitations section.
        for key, value in (attributes or {}).items():
            user_attributes.append({"Name": f"custom:{key}", "Value": value})
        try:
            response = self.client.sign_up(
                ClientId=self.client_id,
                Username=username,
                Password=password,
                UserAttributes=user_attributes,
            )
        except ClientError as exc:
            raise self._translate(exc) from exc
        except BotoCoreError as exc:
            raise errors.ProviderUnavailable() from exc
        return UserProfile(
            username=username,
            email=email,
            name=name,
            subject_id=response.get("UserSub"),
            confirmed=bool(response.get("UserConfirmed", False)),
            attributes=dict(attributes or {}),
        )

    def confirm_sign_up(self, *, username: str, code: str) -> UserProfile:
        try:
            self.client.confirm_sign_up(
                ClientId=self.client_id,
                Username=username,
                ConfirmationCode=code,
            )
        except ClientError as exc:
            raise self._translate(exc) from exc
        except BotoCoreError as exc:
            raise errors.ProviderUnavailable() from exc
        return self.get_user(username=username)

    def sign_in(self, *, username: str, password: str) -> AuthSession:
        try:
            response = self.client.initiate_auth(
                ClientId=self.client_id,
                AuthFlow="USER_PASSWORD_AUTH",
                AuthParameters={"USERNAME": username, "PASSWORD": password},
            )
        except ClientError as exc:
            translated = self._translate(exc)
            # Do not let a wrong username be distinguished from a wrong password.
            if isinstance(translated, errors.UserNotFound):
                translated = errors.InvalidCredentials()
            raise translated from exc
        except BotoCoreError as exc:
            raise errors.ProviderUnavailable() from exc

        result = response.get("AuthenticationResult") or {}
        tokens = AuthTokens(
            access_token=result.get("AccessToken", ""),
            refresh_token=result.get("RefreshToken"),
            id_token=result.get("IdToken"),
            expires_in=result.get("ExpiresIn"),
            token_type=result.get("TokenType", "Bearer"),
        )

        # The ID token already carries sub/email/name. Calling admin_get_user
        # here as well doubled the AWS round trips on the hottest path and ate
        # the pool's admin-API quota for no new information.
        claims = _decode_jwt_claims(tokens.id_token) if tokens.id_token else {}
        if claims.get("sub"):
            profile = UserProfile(
                username=claims.get("cognito:username", username),
                email=claims.get("email"),
                name=claims.get("name"),
                subject_id=claims.get("sub"),
                confirmed=True,
                attributes={
                    key.removeprefix("custom:"): value
                    for key, value in claims.items()
                    if key.startswith("custom:")
                },
            )
        else:
            profile = self.get_user(username=username)
        return AuthSession(profile=profile, tokens=tokens)

    def get_user(self, *, username: str) -> UserProfile:
        try:
            response = self.client.admin_get_user(
                UserPoolId=self.user_pool_id,
                Username=username,
            )
        except ClientError as exc:
            raise self._translate(exc) from exc
        except BotoCoreError as exc:
            raise errors.ProviderUnavailable() from exc
        return UserProfile.from_attribute_list(
            response.get("Username", username),
            response.get("UserAttributes", []),
            confirmed=response.get("UserStatus") == "CONFIRMED",
        )
