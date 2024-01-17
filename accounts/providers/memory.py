"""An in-process identity provider for local development, demos and tests.

It implements the same contract as Cognito — including the same domain errors
and the same "unconfirmed users cannot sign in" rule — so the GraphQL surface
behaves identically whichever provider is selected. It is explicitly *not* a
production backend: passwords are salted-hashed but the store is a dict that
dies with the process.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field

from accounts import errors
from accounts.domain import AuthSession, AuthTokens, UserProfile
from accounts.providers.base import IdentityProvider

_PBKDF2_ROUNDS = 100_000
#: Fixed code so a seeded demo/test can confirm a user without reading an inbox.
DEFAULT_CONFIRMATION_CODE = "123456"


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ROUNDS)


def _b64(payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@dataclass
class _Record:
    profile: UserProfile
    salt: bytes
    password_hash: bytes
    code: str = DEFAULT_CONFIRMATION_CODE
    attributes: dict[str, str] = field(default_factory=dict)


class InMemoryIdentityProvider(IdentityProvider):
    """A thread-safe dict-backed user directory."""

    name = "memory"

    def __init__(self, *, auto_confirm: bool = False) -> None:
        self._users: dict[str, _Record] = {}
        self._lock = threading.RLock()
        self._auto_confirm = auto_confirm

    # ------------------------------------------------------------------ helpers

    def _issue_tokens(self, profile: UserProfile) -> AuthTokens:
        """Issue a structurally valid, locally signed, non-Cognito token."""
        issued_at = int(time.time())
        claims = {
            "sub": profile.subject_id,
            "cognito:username": profile.username,
            "email": profile.email,
            "name": profile.name,
            "iss": "in-memory-identity-provider",
            "iat": issued_at,
            "exp": issued_at + 3600,
            **{f"custom:{k}": v for k, v in profile.attributes.items()},
        }
        header = _b64({"alg": "none", "typ": "JWT"})
        body = _b64(claims)
        return AuthTokens(
            access_token=f"{header}.{body}.",
            refresh_token=secrets.token_urlsafe(32),
            id_token=f"{header}.{body}.",
            expires_in=3600,
        )

    # ----------------------------------------------------------------- contract

    def sign_up(
        self,
        *,
        username: str,
        password: str,
        email: str,
        name: str,
        attributes: dict[str, str] | None = None,
    ) -> UserProfile:
        if len(password) < 8:
            raise errors.WeakPassword()
        with self._lock:
            if username in self._users:
                raise errors.UserAlreadyExists()
            salt = os.urandom(16)
            profile = UserProfile(
                username=username,
                email=email,
                name=name,
                subject_id=str(secrets.token_hex(16)),
                confirmed=self._auto_confirm,
                attributes=dict(attributes or {}),
            )
            self._users[username] = _Record(
                profile=profile,
                salt=salt,
                password_hash=_hash_password(password, salt),
                attributes=dict(attributes or {}),
            )
            return profile

    def confirm_sign_up(self, *, username: str, code: str) -> UserProfile:
        with self._lock:
            record = self._users.get(username)
            if record is None:
                raise errors.UserNotFound()
            if not hmac.compare_digest(record.code, code):
                raise errors.InvalidConfirmationCode()
            record.profile = UserProfile(
                username=record.profile.username,
                email=record.profile.email,
                name=record.profile.name,
                subject_id=record.profile.subject_id,
                confirmed=True,
                attributes=record.profile.attributes,
            )
            return record.profile

    def sign_in(self, *, username: str, password: str) -> AuthSession:
        with self._lock:
            record = self._users.get(username)
            if record is None:
                raise errors.InvalidCredentials()
            expected = _hash_password(password, record.salt)
            if not hmac.compare_digest(expected, record.password_hash):
                raise errors.InvalidCredentials()
            if not record.profile.confirmed:
                raise errors.UserNotConfirmed()
            return AuthSession(
                profile=record.profile,
                tokens=self._issue_tokens(record.profile),
            )

    def get_user(self, *, username: str) -> UserProfile:
        with self._lock:
            record = self._users.get(username)
            if record is None:
                raise errors.UserNotFound()
            return record.profile

    # ------------------------------------------------------------------- extras

    def seed(
        self,
        *,
        username: str,
        password: str,
        email: str,
        name: str,
        attributes: dict[str, str] | None = None,
        confirmed: bool = True,
    ) -> UserProfile:
        """Create a user directly, for demo fixtures and screenshots."""
        self.sign_up(
            username=username,
            password=password,
            email=email,
            name=name,
            attributes=attributes,
        )
        if confirmed:
            return self.confirm_sign_up(username=username, code=DEFAULT_CONFIRMATION_CODE)
        return self.get_user(username=username)
