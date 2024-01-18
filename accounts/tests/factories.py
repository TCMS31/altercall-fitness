"""Shared test helpers."""

from __future__ import annotations

from accounts.ai import FitnessGoal
from accounts.providers import InMemoryIdentityProvider
from accounts.providers.memory import DEFAULT_CONFIRMATION_CODE

PASSWORD = "Str0ng-Test-Pass!"


class CountingProvider(InMemoryIdentityProvider):
    """An in-memory provider that records how many directory calls it served.

    Used to assert the things that actually matter for cost and quota:
    how many round trips a sign-in makes, and whether repeated reads hit the
    cache instead of the directory.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.calls: list[str] = []

    def sign_up(self, **kwargs):
        self.calls.append("sign_up")
        return super().sign_up(**kwargs)

    def confirm_sign_up(self, **kwargs):
        self.calls.append("confirm_sign_up")
        return super().confirm_sign_up(**kwargs)

    def sign_in(self, **kwargs):
        self.calls.append("sign_in")
        return super().sign_in(**kwargs)

    def get_user(self, **kwargs):
        self.calls.append("get_user")
        return super().get_user(**kwargs)

    def count(self, name: str) -> int:
        return self.calls.count(name)


class StubGoalParser:
    """A goal parser that returns a fixed result and records its inputs."""

    name = "stub"

    def __init__(self, goal: FitnessGoal | None = None) -> None:
        self.goal = goal or FitnessGoal(
            goal_type="fat_loss",
            target="5 kg",
            timeframe="3 months",
            sessions_per_week=4,
            summary="Lose 5 kg in 3 months.",
            source="stub",
        )
        self.seen: list[str] = []

    def parse(self, text: str) -> FitnessGoal:
        self.seen.append(text)
        return self.goal


def make_member(
    provider: InMemoryIdentityProvider,
    username: str = "test.member",
    *,
    confirmed: bool = True,
    attributes: dict[str, str] | None = None,
):
    provider.sign_up(
        username=username,
        password=PASSWORD,
        email=f"{username}@example.com",
        name="Test Member",
        attributes=attributes,
    )
    if confirmed:
        return provider.confirm_sign_up(username=username, code=DEFAULT_CONFIRMATION_CODE)
    return provider.get_user(username=username)
