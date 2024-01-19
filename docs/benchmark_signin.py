#!/usr/bin/env python
"""Measure the cost of the sign-in and profile-read paths.

Runs against a **local stub** that speaks the Cognito JSON wire protocol and
sleeps for a fixed interval before replying, so boto3 does real serialisation,
signing, HTTP and parsing — only the AWS network hop is replaced by a
controlled delay. The delay is a stand-in for real Cognito latency, not a
measurement of it; everything else in the numbers is real.

    python docs/benchmark_signin.py --iterations 30 --latency-ms 40

Reported:
  * legacy sign-in  — initiate_auth + admin_get_user (the original code path)
  * current sign-in — initiate_auth only, profile read from the ID token
  * getUser         — uncached vs. served from the profile cache
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import statistics
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "fitness_tracker.settings")
os.environ.setdefault("DJANGO_SECRET_KEY", "benchmark-only")
os.environ.setdefault("AUTH_PROVIDER", "cognito")
os.environ.setdefault("LOG_LEVEL", "ERROR")

import django

django.setup()

from accounts.domain import AuthSession
from accounts.providers.cognito import CognitoIdentityProvider
from accounts.services import AccountService

USERNAME = "rhiannon.pike"


def _segment(payload: dict) -> str:
    raw = json.dumps(payload).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


ID_TOKEN = ".".join(
    [
        _segment({"alg": "RS256", "typ": "JWT"}),
        _segment(
            {
                "sub": "9f1c0f1e-0000-4a7b-9d21-4bd1f3d9c001",
                "cognito:username": USERNAME,
                "email": "rhiannon.pike@example.com",
                "name": "Rhiannon Pike",
                "custom:goal_type": "fat_loss",
            }
        ),
        "signature",
    ]
)

RESPONSES = {
    "InitiateAuth": {
        "AuthenticationResult": {
            "AccessToken": "stub-access-token",
            "RefreshToken": "stub-refresh-token",
            "IdToken": ID_TOKEN,
            "ExpiresIn": 3600,
            "TokenType": "Bearer",
        }
    },
    "AdminGetUser": {
        "Username": USERNAME,
        "UserStatus": "CONFIRMED",
        "UserAttributes": [
            {"Name": "sub", "Value": "9f1c0f1e-0000-4a7b-9d21-4bd1f3d9c001"},
            {"Name": "email", "Value": "rhiannon.pike@example.com"},
            {"Name": "name", "Value": "Rhiannon Pike"},
            {"Name": "custom:goal_type", "Value": "fat_loss"},
        ],
    },
}


class StubCognitoHandler(BaseHTTPRequestHandler):
    latency_seconds = 0.04
    counter: ClassVar[dict[str, int]] = {}

    def do_POST(self) -> None:  # http.server's required method name
        target = self.headers.get("X-Amz-Target", "").split(".")[-1]
        self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        type(self).counter[target] = type(self).counter.get(target, 0) + 1
        time.sleep(type(self).latency_seconds)
        body = json.dumps(RESPONSES.get(target, {})).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/x-amz-json-1.1")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # silence the default access log
        return


class LegacyCognitoProvider(CognitoIdentityProvider):
    """The original sign-in: authenticate, then look the profile up again."""

    def sign_in(self, *, username: str, password: str) -> AuthSession:
        from accounts.domain import AuthTokens

        response = self.client.initiate_auth(
            ClientId=self.client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={"USERNAME": username, "PASSWORD": password},
        )
        result = response["AuthenticationResult"]
        tokens = AuthTokens(
            access_token=result["AccessToken"],
            refresh_token=result.get("RefreshToken"),
            id_token=result.get("IdToken"),
            expires_in=result.get("ExpiresIn"),
        )
        return AuthSession(profile=self.get_user(username=username), tokens=tokens)


def timed(fn, iterations: int) -> tuple[float, float]:
    samples = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000)
    return statistics.median(samples), statistics.mean(samples)


def build(cls, endpoint: str):
    return cls(
        region="eu-north-1",
        user_pool_id="eu-north-1_BENCHMARK",
        client_id="benchmark-client",
        access_key_id="stub",
        secret_access_key="stub",
        endpoint_url=endpoint,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--latency-ms", type=float, default=40.0)
    parser.add_argument("--port", type=int, default=8551)
    args = parser.parse_args()

    StubCognitoHandler.latency_seconds = args.latency_ms / 1000.0
    server = ThreadingHTTPServer(("127.0.0.1", args.port), StubCognitoHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{args.port}"

    from django.core.cache import cache

    legacy = build(LegacyCognitoProvider, endpoint)
    current = build(CognitoIdentityProvider, endpoint)

    print(
        f"stub Cognito on {endpoint}, injected latency {args.latency_ms:.0f} ms/call, "
        f"{args.iterations} iterations\n"
    )
    header = f"{'path':<34}{'calls/op':>10}{'median ms':>12}{'mean ms':>10}"
    print(header)
    print("-" * len(header))

    StubCognitoHandler.counter.clear()
    median, mean = timed(lambda: legacy.sign_in(username=USERNAME, password="pw"), args.iterations)
    calls = sum(StubCognitoHandler.counter.values()) / args.iterations
    print(f"{'signin (legacy, 2 AWS calls)':<34}{calls:>10.1f}{median:>12.1f}{mean:>10.1f}")

    StubCognitoHandler.counter.clear()
    median_new, mean_new = timed(
        lambda: current.sign_in(username=USERNAME, password="pw"), args.iterations
    )
    calls_new = sum(StubCognitoHandler.counter.values()) / args.iterations
    print(
        f"{'signin (current, 1 AWS call)':<34}{calls_new:>10.1f}"
        f"{median_new:>12.1f}{mean_new:>10.1f}"
    )

    cache.clear()
    uncached = AccountService(provider=current, cache_ttl=0)
    StubCognitoHandler.counter.clear()
    median_u, mean_u = timed(lambda: uncached.find_user(username=USERNAME), args.iterations)
    calls_u = sum(StubCognitoHandler.counter.values()) / args.iterations
    print(f"{'getUser (cache off)':<34}{calls_u:>10.1f}{median_u:>12.1f}{mean_u:>10.1f}")

    cache.clear()
    cached = AccountService(provider=current, cache_ttl=60)
    cached.find_user(username=USERNAME)  # warm
    StubCognitoHandler.counter.clear()
    median_c, mean_c = timed(lambda: cached.find_user(username=USERNAME), args.iterations)
    calls_c = sum(StubCognitoHandler.counter.values()) / args.iterations
    print(f"{'getUser (cache on, warm)':<34}{calls_c:>10.1f}{median_c:>12.1f}{mean_c:>10.1f}")

    print(
        f"\nsign-in: {median:.1f} ms -> {median_new:.1f} ms median "
        f"({(1 - median_new / median) * 100:.0f}% faster, "
        f"{calls:.0f} -> {calls_new:.0f} AWS calls per sign-in)"
    )
    print(
        f"getUser: {median_u:.1f} ms -> {median_c:.2f} ms median "
        f"({calls_u:.0f} -> {calls_c:.0f} AWS calls per read)"
    )
    server.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
