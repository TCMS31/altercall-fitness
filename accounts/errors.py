"""Domain errors raised by the identity layer.

The GraphQL layer maps these onto stable, client-facing error codes. Provider
SDK exceptions (``botocore.exceptions.ClientError`` and friends) must never
escape ``accounts.providers`` — they leak vendor detail and, in Cognito's case,
wording that lets an attacker distinguish "no such user" from "wrong password".
"""

from __future__ import annotations


class IdentityError(Exception):
    """Base class for every failure the identity layer reports.

    ``code`` is part of the public API: clients branch on it, so it must stay
    stable even if the underlying provider changes.
    """

    code = "IDENTITY_ERROR"
    message = "The identity provider could not complete the request."

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.message)


class UserNotFound(IdentityError):
    code = "USER_NOT_FOUND"
    message = "No account matches that username."


class UserAlreadyExists(IdentityError):
    code = "USER_ALREADY_EXISTS"
    message = "An account with that username already exists."


class InvalidCredentials(IdentityError):
    """Raised for a bad username *or* a bad password.

    Deliberately indistinguishable between the two cases so the endpoint cannot
    be used to enumerate accounts.
    """

    code = "INVALID_CREDENTIALS"
    message = "Username or password is incorrect."


class UserNotConfirmed(IdentityError):
    code = "USER_NOT_CONFIRMED"
    message = "This account has not been confirmed yet. Check your email for the code."


class InvalidConfirmationCode(IdentityError):
    code = "INVALID_CONFIRMATION_CODE"
    message = "That confirmation code is not valid or has expired."


class WeakPassword(IdentityError):
    code = "WEAK_PASSWORD"
    message = "The password does not meet the configured password policy."


class TooManyRequests(IdentityError):
    code = "TOO_MANY_REQUESTS"
    message = "Too many attempts. Please wait a moment and try again."


class ProviderUnavailable(IdentityError):
    """The provider is misconfigured or unreachable.

    Notably raised when ``AUTH_PROVIDER=cognito`` but the AWS settings are
    missing, instead of letting ``botocore.NoRegionError`` escape as a 500.
    """

    code = "PROVIDER_UNAVAILABLE"
    message = "The identity provider is not configured or is unreachable."
