"""Goal parsing: deterministic rules, and the Claude path with a fake client.

No test in this module makes a network call. The Claude parser is exercised
against hand-built response objects.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from accounts.ai import ClaudeGoalParser, RuleBasedGoalParser, get_goal_parser


def fake_response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


class FakeClient:
    """Stands in for ``anthropic.Anthropic`` — records calls, returns canned text."""

    def __init__(self, text: str | None = None, error: Exception | None = None) -> None:
        self._text = text
        self._error = error
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self._error is not None:
            raise self._error
        return fake_response(self._text)


class RuleBasedGoalParserTests(SimpleTestCase):
    def setUp(self) -> None:
        self.parser = RuleBasedGoalParser()

    def test_extracts_type_target_timeframe_and_volume(self):
        goal = self.parser.parse(
            "I want to lose 6 kg in 3 months and I can train four times a week"
        )
        self.assertEqual(goal.goal_type, "fat_loss")
        self.assertEqual(goal.target, "6 kg")
        self.assertEqual(goal.timeframe, "3 months")
        self.assertEqual(goal.sessions_per_week, 4)
        self.assertEqual(goal.source, "rules")

    def test_classifies_each_goal_family(self):
        cases = {
            "put on muscle mass": "muscle_gain",
            "run a half marathon": "endurance",
            "get my deadlift stronger": "strength",
            "improve my hip mobility": "mobility",
            "just feel better day to day": "general_fitness",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.parser.parse(text).goal_type, expected)

    def test_numeric_session_counts_are_understood(self):
        self.assertEqual(self.parser.parse("training 5 days a week").sessions_per_week, 5)
        self.assertEqual(self.parser.parse("3x per week").sessions_per_week, 3)

    def test_implausible_session_counts_are_discarded(self):
        self.assertIsNone(self.parser.parse("40 times a week").sessions_per_week)

    def test_empty_input_is_handled(self):
        goal = self.parser.parse("")
        self.assertEqual(goal.goal_type, "general_fitness")
        self.assertIsNone(goal.target)

    def test_attributes_omit_missing_values(self):
        goal = self.parser.parse("just feel better")
        self.assertEqual(goal.as_attributes(), {"goal_type": "general_fitness"})

    def test_long_input_summary_is_truncated(self):
        goal = self.parser.parse("lose weight " * 40)
        self.assertLessEqual(len(goal.summary), 120)


@override_settings(AI_MODEL="claude-opus-5")
class ClaudeGoalParserTests(SimpleTestCase):
    def test_uses_the_structured_json_reply(self):
        client = FakeClient(
            '{"goal_type": "endurance", "target": "sub-25:00 5k",'
            ' "timeframe": "8 weeks", "sessions_per_week": 3,'
            ' "summary": "Run a sub-25 minute 5k within 8 weeks."}'
        )
        goal = ClaudeGoalParser(client=client).parse("I want to get faster over 5k")

        self.assertEqual(goal.goal_type, "endurance")
        self.assertEqual(goal.target, "sub-25:00 5k")
        self.assertEqual(goal.sessions_per_week, 3)
        self.assertEqual(goal.source, "claude")
        self.assertEqual(client.calls[0]["model"], "claude-opus-5")

    def test_tolerates_a_fenced_code_block(self):
        client = FakeClient('```json\n{"goal_type": "strength", "summary": "Get strong."}\n```')
        self.assertEqual(ClaudeGoalParser(client=client).parse("stronger").goal_type, "strength")

    def test_rejects_an_out_of_vocabulary_goal_type(self):
        client = FakeClient('{"goal_type": "become_a_wizard", "summary": "?"}')
        goal = ClaudeGoalParser(client=client).parse("something odd")
        self.assertEqual(goal.goal_type, "general_fitness")

    def test_rejects_an_implausible_session_count(self):
        client = FakeClient('{"goal_type": "strength", "sessions_per_week": 99, "summary": "x"}')
        self.assertIsNone(ClaudeGoalParser(client=client).parse("lift").sessions_per_week)

    def test_falls_back_to_rules_on_malformed_json(self):
        client = FakeClient("I'm afraid I can't do that.")
        goal = ClaudeGoalParser(client=client).parse("lose 4 kg in 2 months")
        self.assertEqual(goal.source, "rules")
        self.assertEqual(goal.target, "4 kg")

    def test_falls_back_to_rules_when_the_api_raises(self):
        client = FakeClient(error=RuntimeError("rate limited"))
        goal = ClaudeGoalParser(client=client).parse("run a marathon in 6 months")
        self.assertEqual(goal.source, "rules")
        self.assertEqual(goal.goal_type, "endurance")

    def test_empty_input_never_calls_the_api(self):
        client = FakeClient("{}")
        ClaudeGoalParser(client=client).parse("   ")
        self.assertEqual(client.calls, [])


class GoalParserSelectionTests(SimpleTestCase):
    @override_settings(AI_GOAL_PARSER="rules", ANTHROPIC_API_KEY="sk-ant-whatever")
    def test_rules_selected_by_default(self):
        self.assertIsInstance(get_goal_parser(), RuleBasedGoalParser)

    @override_settings(AI_GOAL_PARSER="claude", ANTHROPIC_API_KEY=None)
    def test_claude_requested_without_a_key_degrades_to_rules(self):
        self.assertIsInstance(get_goal_parser(), RuleBasedGoalParser)

    @override_settings(AI_GOAL_PARSER="claude", ANTHROPIC_API_KEY="")
    def test_blank_key_degrades_to_rules(self):
        self.assertIsInstance(get_goal_parser(), RuleBasedGoalParser)
