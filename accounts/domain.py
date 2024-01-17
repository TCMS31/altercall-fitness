"""Provider-agnostic value objects.

Nothing in this module imports Django, boto3 or graphene. Everything above it
(providers, services, schema) depends on these types rather than on each other,
which is what lets a second identity provider drop in without touching the API.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

#: Attribute keys the service layer writes to a user profile during onboarding.
GOAL_ATTRIBUTES = ("goal_type", "goal_target", "goal_timeframe", "sessions_per_week")


@dataclass(frozen=True, slots=True)
class UserProfile:
    """A user as the API exposes them, independent of the backing directory."""

    username: str
    email: str | None = None
    name: str | None = None
    subject_id: str | None = None
    confirmed: bool = False
    attributes: Mapping[str, str] = field(default_factory=dict)

    def with_attributes(self, **extra: str) -> UserProfile:
        merged = {**self.attributes, **{k: v for k, v in extra.items() if v is not None}}
        return replace(self, attributes=merged)

    @classmethod
    def from_attribute_list(
        cls,
        username: str,
        attribute_list: list[Mapping[str, Any]],
        *,
        confirmed: bool = False,
    ) -> UserProfile:
        """Build a profile from Cognito's ``[{'Name': ..., 'Value': ...}]`` shape."""
        attrs = {item["Name"]: item["Value"] for item in attribute_list}
        return cls(
            username=username,
            email=attrs.get("email"),
            name=attrs.get("name"),
            subject_id=attrs.get("sub"),
            confirmed=confirmed,
            attributes={
                key.removeprefix("custom:"): value
                for key, value in attrs.items()
                if key.startswith("custom:")
            },
        )


@dataclass(frozen=True, slots=True)
class AuthTokens:
    """The token triple returned by a successful sign-in."""

    access_token: str
    refresh_token: str | None = None
    id_token: str | None = None
    expires_in: int | None = None
    token_type: str = "Bearer"


@dataclass(frozen=True, slots=True)
class AuthSession:
    """A successful sign-in: who signed in, and the tokens they may use."""

    profile: UserProfile
    tokens: AuthTokens
