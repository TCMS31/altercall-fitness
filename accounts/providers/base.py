"""The identity provider seam.

This is the one extension point the project is built around: everything above
it (services, GraphQL, tests) talks to :class:`IdentityProvider` and never to
boto3. Adding Auth0, Keycloak or a plain Django-model backend means writing one
class here and registering it — no other file changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from accounts.domain import AuthSession, UserProfile


class IdentityProvider(ABC):
    """A user directory that can register, confirm and authenticate users."""

    #: Short, stable name used by ``AUTH_PROVIDER`` and in diagnostics.
    name: str = "base"

    @abstractmethod
    def sign_up(
        self,
        *,
        username: str,
        password: str,
        email: str,
        name: str,
        attributes: dict[str, str] | None = None,
    ) -> UserProfile:
        """Register a new, unconfirmed user.

        Raises:
            UserAlreadyExists: the username is taken.
            WeakPassword: the password fails the provider's policy.
        """

    @abstractmethod
    def confirm_sign_up(self, *, username: str, code: str) -> UserProfile:
        """Confirm a registration with the one-time code sent to the user.

        Raises:
            InvalidConfirmationCode: the code is wrong or expired.
            UserNotFound: no such user.
        """

    @abstractmethod
    def sign_in(self, *, username: str, password: str) -> AuthSession:
        """Authenticate a user and return their profile plus fresh tokens.

        Implementations must resolve the profile without a second directory
        round trip where the protocol already carries it (see
        :mod:`accounts.providers.cognito`).

        Raises:
            InvalidCredentials: bad username or password.
            UserNotConfirmed: the account exists but was never confirmed.
        """

    @abstractmethod
    def get_user(self, *, username: str) -> UserProfile:
        """Look up a user by username.

        Raises:
            UserNotFound: no such user.
        """

    def health(self) -> bool:
        """Cheap readiness probe. Overridden where a real check is possible."""
        return True
