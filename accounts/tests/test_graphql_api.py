"""End-to-end GraphQL tests driven through the real HTTP endpoint."""

from __future__ import annotations

import json

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from accounts.errors import UserNotFound
from accounts.providers import get_identity_provider, reset_cache
from accounts.providers.memory import DEFAULT_CONFIRMATION_CODE

PASSWORD = "Str0ng-Test-Pass!"

SIGNUP = """
mutation ($u: String!, $n: String!, $p: String!, $e: String!, $g: String) {
  signup(username: $u, name: $n, password: $p, email: $e, goal: $g) {
    user { username email confirmed goalType goalTarget sessionsPerWeek }
    goal { goalType target timeframe sessionsPerWeek source }
  }
}
"""

CONFIRM = """
mutation ($u: String!, $o: String!) {
  confirmUser(username: $u, otp: $o) { success user { username confirmed } }
}
"""

SIGNIN = """
mutation ($u: String!, $p: String!) {
  signin(username: $u, password: $p) {
    accessToken refreshToken expiresIn
    user { id username email goalType }
  }
}
"""

GET_USER = """
query ($u: String!) { getUser(username: $u) { username email confirmed goalType } }
"""


@override_settings(AUTH_PROVIDER="memory", AI_GOAL_PARSER="rules", GRAPHIQL_ENABLED=True)
class GraphQLApiTests(SimpleTestCase):
    def setUp(self) -> None:
        reset_cache()
        cache.clear()
        self.addCleanup(reset_cache)
        self.addCleanup(cache.clear)

    def execute(self, query: str, **variables):
        response = self.client.post(
            "/graphql",
            data=json.dumps({"query": query, "variables": variables}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return json.loads(response.content)

    def register(self, username="ada", goal=None):
        return self.execute(
            SIGNUP,
            u=username,
            n="Ada Lovelace",
            p=PASSWORD,
            e=f"{username}@example.com",
            g=goal,
        )

    # ------------------------------------------------------------------ flows

    def test_full_signup_confirm_signin_flow(self):
        signup = self.register(goal="lose 6 kg in 3 months training four times a week")
        self.assertIsNone(signup.get("errors"))
        user = signup["data"]["signup"]["user"]
        self.assertEqual(user["username"], "ada")
        self.assertFalse(user["confirmed"])
        self.assertEqual(user["goalType"], "fat_loss")
        self.assertEqual(signup["data"]["signup"]["goal"]["target"], "6 kg")
        self.assertEqual(signup["data"]["signup"]["goal"]["sessionsPerWeek"], 4)
        self.assertEqual(signup["data"]["signup"]["goal"]["source"], "rules")

        confirmed = self.execute(CONFIRM, u="ada", o=DEFAULT_CONFIRMATION_CODE)
        self.assertTrue(confirmed["data"]["confirmUser"]["success"])
        self.assertTrue(confirmed["data"]["confirmUser"]["user"]["confirmed"])

        signin = self.execute(SIGNIN, u="ada", p=PASSWORD)
        payload = signin["data"]["signin"]
        self.assertTrue(payload["accessToken"])
        self.assertTrue(payload["refreshToken"])
        self.assertEqual(payload["expiresIn"], 3600)
        self.assertEqual(payload["user"]["username"], "ada")
        self.assertEqual(payload["user"]["goalType"], "fat_loss")

        fetched = self.execute(GET_USER, u="ada")
        self.assertEqual(fetched["data"]["getUser"]["email"], "ada@example.com")
        self.assertTrue(fetched["data"]["getUser"]["confirmed"])

    def test_signup_without_a_goal_returns_a_null_goal(self):
        result = self.register(username="bob")
        self.assertIsNone(result["data"]["signup"]["goal"])
        self.assertIsNone(result["data"]["signup"]["user"]["goalType"])

    def test_preview_goal_does_not_create_an_account(self):
        result = self.execute(
            "query ($t: String!) { previewGoal(text: $t) { goalType target source } }",
            t="add muscle over the next 6 months",
        )
        self.assertEqual(result["data"]["previewGoal"]["goalType"], "muscle_gain")
        with self.assertRaises(UserNotFound):
            get_identity_provider().get_user(username="anyone")

    # ----------------------------------------------------------------- errors

    def test_errors_carry_a_stable_code_and_no_provider_detail(self):
        self.register()
        duplicate = self.register()
        error = duplicate["errors"][0]
        self.assertEqual(error["extensions"]["code"], "USER_ALREADY_EXISTS")
        self.assertNotIn("botocore", json.dumps(duplicate).lower())

    def test_unknown_user_lookup_reports_user_not_found(self):
        result = self.execute(GET_USER, u="nobody")
        self.assertEqual(result["errors"][0]["extensions"]["code"], "USER_NOT_FOUND")

    def test_unconfirmed_sign_in_is_reported_distinctly(self):
        self.register()
        result = self.execute(SIGNIN, u="ada", p=PASSWORD)
        self.assertEqual(result["errors"][0]["extensions"]["code"], "USER_NOT_CONFIRMED")

    def test_bad_password_and_unknown_user_return_the_same_message(self):
        self.register()
        self.execute(CONFIRM, u="ada", o=DEFAULT_CONFIRMATION_CODE)
        wrong = self.execute(SIGNIN, u="ada", p="Wr0ng-Pass!!")
        unknown = self.execute(SIGNIN, u="ghost", p="Wr0ng-Pass!!")
        self.assertEqual(wrong["errors"][0]["message"], unknown["errors"][0]["message"])
        self.assertEqual(wrong["errors"][0]["extensions"]["code"], "INVALID_CREDENTIALS")

    def test_wrong_otp_is_reported(self):
        self.register()
        result = self.execute(CONFIRM, u="ada", o="000000")
        self.assertEqual(result["errors"][0]["extensions"]["code"], "INVALID_CONFIRMATION_CODE")

    # --------------------------------------------------------------- routing

    def test_both_slashed_and_unslashed_graphql_paths_are_routed(self):
        for path in ("/graphql", "/graphql/"):
            with self.subTest(path=path):
                response = self.client.post(
                    path,
                    data=json.dumps({"query": "{ authProvider }"}),
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(json.loads(response.content)["data"]["authProvider"], "memory")

    def test_graphiql_is_served_for_browser_requests(self):
        response = self.client.get("/graphql", HTTP_ACCEPT="text/html")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"graphiql", response.content.lower())


@override_settings(AUTH_PROVIDER="memory")
class HealthEndpointTests(SimpleTestCase):
    def setUp(self) -> None:
        reset_cache()
        self.addCleanup(reset_cache)

    def test_memory_provider_reports_ok(self):
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["provider"], "memory")

    @override_settings(
        AUTH_PROVIDER="cognito",
        COGNITO_REGION=None,
        COGNITO_USER_POOL_ID=None,
        COGNITO_CLIENT_ID=None,
    )
    def test_unconfigured_cognito_reports_degraded_with_503(self):
        reset_cache()
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(json.loads(response.content)["status"], "degraded")
