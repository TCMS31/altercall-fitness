"""Application services — the only place account business rules live.

The GraphQL resolvers below this are deliberately dumb: they validate nothing,
decide nothing and know nothing about Cognito. Everything a second transport
(REST, a management command, a worker) would need to reuse is here.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache

from accounts import errors
from accounts.ai import FitnessGoal, GoalParser, get_goal_parser
from accounts.domain import AuthSession, UserProfile
from accounts.providers import IdentityProvider, get_identity_provider

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "accounts:profile:"


class AccountService:
    """Registration, confirmation, sign-in and profile lookup."""

    def __init__(
        self,
        provider: IdentityProvider | None = None,
        goal_parser: GoalParser | None = None,
        *,
        cache_ttl: int | None = None,
    ) -> None:
        self._provider = provider
        self._goal_parser = goal_parser
        self._cache_ttl = settings.PROFILE_CACHE_TTL if cache_ttl is None else cache_ttl

    @property
    def provider(self) -> IdentityProvider:
        if self._provider is None:
            self._provider = get_identity_provider()
        return self._provider

    @property
    def goal_parser(self) -> GoalParser:
        if self._goal_parser is None:
            self._goal_parser = get_goal_parser()
        return self._goal_parser

    # ------------------------------------------------------------------- cache

    @staticmethod
    def _cache_key(username: str) -> str:
        return f"{_CACHE_PREFIX}{username}"

    def _remember(self, profile: UserProfile) -> UserProfile:
        if self._cache_ttl > 0:
            cache.set(self._cache_key(profile.username), profile, self._cache_ttl)
        return profile

    def forget(self, username: str) -> None:
        cache.delete(self._cache_key(username))

    # ---------------------------------------------------------------- commands

    def register(
        self,
        *,
        username: str,
        password: str,
        email: str,
        name: str,
        goal: str | None = None,
    ) -> tuple[UserProfile, FitnessGoal | None]:
        """Register a user, attaching structured onboarding attributes.

        ``goal`` is free text. It is parsed into attributes before the account
        is created so the coaching side has something to plan against from the
        first session. Parsing never blocks registration: the parser degrades to
        deterministic rules when AI is unavailable.
        """
        username = _require(username, "username")
        email = _require(email, "email")
        parsed_goal = self.goal_parser.parse(goal) if goal and goal.strip() else None
        attributes = parsed_goal.as_attributes() if parsed_goal else {}
        profile = self.provider.sign_up(
            username=username,
            password=password,
            email=email,
            name=name,
            attributes=attributes,
        )
        self.forget(username)
        return profile, parsed_goal

    def confirm(self, *, username: str, code: str) -> UserProfile:
        profile = self.provider.confirm_sign_up(
            username=_require(username, "username"), code=_require(code, "code")
        )
        return self._remember(profile)

    def authenticate(self, *, username: str, password: str) -> AuthSession:
        """Sign a user in.

        The provider resolves the profile from the tokens it was already given,
        so this is a single call to the directory, not two. The profile is then
        warmed into the cache, which is why an immediate ``getUser`` after a
        sign-in costs nothing.
        """
        session = self.provider.sign_in(username=_require(username, "username"), password=password)
        self._remember(session.profile)
        return session

    # ----------------------------------------------------------------- queries

    def find_user(self, *, username: str) -> UserProfile:
        """Look up a profile, serving repeats from cache.

        Cognito's admin APIs are quota-limited per user pool, and a profile is
        read far more often than it changes, so an unbounded read-through of
        every ``getUser`` query is the first thing to fall over under load.
        """
        username = _require(username, "username")
        key = self._cache_key(username)
        cached = cache.get(key)
        if cached is not None:
            return cached
        return self._remember(self.provider.get_user(username=username))

    def preview_goal(self, text: str) -> FitnessGoal:
        """Parse a goal without creating anything — used by the sign-up form."""
        return self.goal_parser.parse(text)


def _require(value: str | None, field: str) -> str:
    value = (value or "").strip()
    if not value:
        raise errors.IdentityError(f"{field} is required.")
    return value
