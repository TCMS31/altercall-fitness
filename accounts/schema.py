"""GraphQL surface for the accounts app.

Resolvers here are intentionally thin: translate arguments, call
:class:`~accounts.services.AccountService`, translate the result or the error.
No business rule, no boto3 call and no configuration lookup belongs in this
module.
"""

from __future__ import annotations

import functools
import logging

import graphene
from graphql import GraphQLError

from accounts import errors
from accounts.domain import AuthSession, UserProfile
from accounts.services import AccountService

logger = logging.getLogger(__name__)


def _service() -> AccountService:
    return AccountService()


def handles_identity_errors(func):
    """Map domain errors onto GraphQL errors carrying a stable ``code``.

    Without this every resolver returned ``str(ClientError)`` to the client,
    which leaked the AWS request id, the pool id and Cognito's own wording —
    enough to tell "no such user" apart from "wrong password".
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except errors.IdentityError as exc:
            raise GraphQLError(
                str(exc),
                extensions={"code": exc.code},
            ) from exc

    return wrapper


# --------------------------------------------------------------------- types


class FitnessGoalType(graphene.ObjectType):
    """A free-text goal after structuring."""

    goal_type = graphene.String(
        description="One of fat_loss, muscle_gain, endurance, strength, mobility, general_fitness."
    )
    target = graphene.String(
        description="Measurable target, e.g. '5 kg'. Null when none was stated."
    )
    timeframe = graphene.String(description="e.g. '3 months'. Null when none was stated.")
    sessions_per_week = graphene.Int(description="Planned weekly training sessions, 1-14.")
    summary = graphene.String(description="One-sentence restatement of the goal.")
    source = graphene.String(description="'claude' when AI parsed it, 'rules' otherwise.")


class UserType(graphene.ObjectType):
    id = graphene.String(description="Provider subject identifier (Cognito 'sub').")
    name = graphene.String()
    username = graphene.String()
    email = graphene.String()
    confirmed = graphene.Boolean(description="Whether the account has completed OTP confirmation.")
    goal_type = graphene.String()
    goal_target = graphene.String()
    goal_timeframe = graphene.String()
    sessions_per_week = graphene.String()

    @classmethod
    def from_profile(cls, profile: UserProfile) -> UserType:
        attrs = profile.attributes or {}
        return cls(
            id=profile.subject_id,
            name=profile.name,
            username=profile.username,
            email=profile.email,
            confirmed=profile.confirmed,
            goal_type=attrs.get("goal_type"),
            goal_target=attrs.get("goal_target"),
            goal_timeframe=attrs.get("goal_timeframe"),
            sessions_per_week=attrs.get("sessions_per_week"),
        )


def _goal_payload(goal) -> FitnessGoalType | None:
    if goal is None:
        return None
    return FitnessGoalType(**goal.as_dict())


# ------------------------------------------------------------------- queries


class Query(graphene.ObjectType):
    get_user = graphene.Field(
        UserType,
        username=graphene.String(required=True),
        description="Fetch a single user profile. Cached for PROFILE_CACHE_TTL seconds.",
    )
    preview_goal = graphene.Field(
        FitnessGoalType,
        text=graphene.String(required=True),
        description="Structure a free-text fitness goal without creating an account.",
    )
    auth_provider = graphene.String(description="Name of the active identity provider.")

    @handles_identity_errors
    def resolve_get_user(self, info, username):
        return UserType.from_profile(_service().find_user(username=username))

    def resolve_preview_goal(self, info, text):
        return _goal_payload(_service().preview_goal(text))

    def resolve_auth_provider(self, info):
        return _service().provider.name


# ----------------------------------------------------------------- mutations


class SignupMutation(graphene.Mutation):
    class Arguments:
        username = graphene.String(required=True)
        name = graphene.String(required=True)
        password = graphene.String(required=True)
        email = graphene.String(required=True)
        goal = graphene.String(
            required=False,
            description="Optional free-text fitness goal, structured during onboarding.",
        )

    user = graphene.Field(UserType)
    goal = graphene.Field(FitnessGoalType)

    @staticmethod
    @handles_identity_errors
    def mutate(root, info, username, name, password, email, goal=None):
        profile, parsed_goal = _service().register(
            username=username, password=password, email=email, name=name, goal=goal
        )
        return SignupMutation(user=UserType.from_profile(profile), goal=_goal_payload(parsed_goal))


class UserConfirmationMutation(graphene.Mutation):
    class Arguments:
        username = graphene.String(required=True)
        otp = graphene.String(required=True)

    success = graphene.Boolean()
    user = graphene.Field(UserType)

    @staticmethod
    @handles_identity_errors
    def mutate(root, info, username, otp):
        profile = _service().confirm(username=username, code=otp)
        return UserConfirmationMutation(success=True, user=UserType.from_profile(profile))


class SigninMutation(graphene.Mutation):
    class Arguments:
        username = graphene.String(required=True)
        password = graphene.String(required=True)

    accessToken = graphene.String()
    refreshToken = graphene.String()
    expiresIn = graphene.Int(description="Access token lifetime in seconds.")
    user = graphene.Field(UserType)

    # Retained so existing clients keep working; prefer the `user` field.
    userId = graphene.String(deprecation_reason="Use `user { id }`.")
    userName = graphene.String(deprecation_reason="Use `user { username }`.")
    userEmail = graphene.String(deprecation_reason="Use `user { email }`.")

    @staticmethod
    @handles_identity_errors
    def mutate(root, info, username, password):
        session: AuthSession = _service().authenticate(username=username, password=password)
        profile = session.profile
        return SigninMutation(
            accessToken=session.tokens.access_token,
            refreshToken=session.tokens.refresh_token,
            expiresIn=session.tokens.expires_in,
            user=UserType.from_profile(profile),
            userId=profile.subject_id,
            userName=profile.username,
            userEmail=profile.email,
        )


class Mutation(graphene.ObjectType):
    signup = SignupMutation.Field()
    signin = SigninMutation.Field()
    confirm_user = UserConfirmationMutation.Field()


schema = graphene.Schema(query=Query, mutation=Mutation)
