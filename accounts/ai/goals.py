"""Turn a free-text fitness goal into structured onboarding attributes.

Sign-up asks one open question — *"what do you want to achieve?"* — instead of
four dropdowns. This module converts the answer into the four attributes the
rest of the platform indexes on (goal type, target, timeframe, weekly training
volume) so the coaching side has something to plan against.

Two implementations share one interface:

* :class:`RuleBasedGoalParser` — deterministic regex/keyword extraction. Always
  available, needs no network, no key, and costs nothing.
* :class:`ClaudeGoalParser` — asks Claude for the same JSON shape, which copes
  with phrasing the rules miss ("I want to be able to keep up with my kids").

Selection is automatic: Claude is used only when ``AI_GOAL_PARSER=claude`` *and*
a key is resolvable *and* the SDK is installed. Every other case, including a
malformed or failed API response, falls back to the rule-based parser, so the
app and the test suite behave identically with no API key set.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from typing import Protocol

from django.conf import settings

logger = logging.getLogger(__name__)

GOAL_TYPES = (
    "fat_loss",
    "muscle_gain",
    "endurance",
    "strength",
    "mobility",
    "general_fitness",
)

_GOAL_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("fat_loss", ("lose weight", "lose ", "fat loss", "slim", "cut", "leaner", "shed")),
    ("muscle_gain", ("muscle", "bulk", "gain weight", "hypertrophy", "size", "mass")),
    (
        "endurance",
        (
            "marathon",
            "5k",
            "10k",
            "half marathon",
            "run",
            "cycling",
            "endurance",
            "cardio",
            "triathlon",
        ),
    ),
    ("strength", ("strength", "stronger", "deadlift", "squat", "bench", "powerlift", "1rm")),
    ("mobility", ("mobility", "flexib", "stretch", "yoga", "posture", "back pain")),
)

_TARGET_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kg|kgs|kilograms?|lbs?|pounds?|km|k\b|miles?|%)",
    re.IGNORECASE,
)
_SESSIONS_RE = re.compile(
    r"(?P<count>\d+|one|two|three|four|five|six|seven)\s*"
    r"(?:times?|sessions?|days?|x)?\s*(?:a|per|each)\s*week",
    re.IGNORECASE,
)
_TIMEFRAME_RE = re.compile(
    r"(?:in|within|over|by|before)\s+(?P<phrase>"
    r"(?:the\s+)?next\s+\d+\s+(?:days?|weeks?|months?|years?)"
    r"|\d+\s*(?:days?|weeks?|months?|years?)"
    r"|(?:january|february|march|april|may|june|july|august|september|october|november|december)"
    r"|summer|winter|spring|autumn|fall|christmas|new year)",
    re.IGNORECASE,
)
_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
}

_SYSTEM_PROMPT = (
    "You extract structured onboarding data from a gym member's free-text fitness goal.\n"
    "Reply with a single JSON object and nothing else, using exactly these keys:\n"
    '  "goal_type": one of ' + ", ".join(GOAL_TYPES) + "\n"
    '  "target": a short measurable target such as "5 kg" or "sub-25:00 5k", or null\n'
    '  "timeframe": a short phrase such as "3 months" or "by June", or null\n'
    '  "sessions_per_week": an integer 1-14, or null\n'
    '  "summary": one sentence, under 120 characters, restating the goal as a coach would.\n'
    "Never invent a target, timeframe or session count the member did not imply."
)


@dataclass(frozen=True, slots=True)
class FitnessGoal:
    """The structured form of a member's stated goal."""

    goal_type: str = "general_fitness"
    target: str | None = None
    timeframe: str | None = None
    sessions_per_week: int | None = None
    summary: str = ""
    #: Which parser produced this — "rules" or "claude". Surfaced in the API so
    #: a client can show "AI-assisted" only when it genuinely was.
    source: str = "rules"

    def as_attributes(self) -> dict[str, str]:
        """Flatten to the string map the identity provider stores."""
        values = {
            "goal_type": self.goal_type,
            "goal_target": self.target,
            "goal_timeframe": self.timeframe,
            "sessions_per_week": (str(self.sessions_per_week) if self.sessions_per_week else None),
        }
        return {key: value for key, value in values.items() if value}

    def as_dict(self) -> dict:
        return asdict(self)


class GoalParser(Protocol):
    """Anything that can turn free text into a :class:`FitnessGoal`."""

    name: str

    def parse(self, text: str) -> FitnessGoal: ...


class RuleBasedGoalParser:
    """Deterministic keyword and regex extraction. The always-available default."""

    name = "rules"

    def parse(self, text: str) -> FitnessGoal:
        cleaned = (text or "").strip()
        if not cleaned:
            return FitnessGoal(summary="No goal provided.", source=self.name)
        lowered = cleaned.lower()

        goal_type = "general_fitness"
        for candidate, keywords in _GOAL_KEYWORDS:
            if any(keyword in lowered for keyword in keywords):
                goal_type = candidate
                break

        target = None
        if match := _TARGET_RE.search(cleaned):
            target = f"{match.group('value')} {match.group('unit').lower()}".replace(" %", "%")

        timeframe = None
        if match := _TIMEFRAME_RE.search(cleaned):
            timeframe = match.group("phrase").strip()

        sessions = None
        if match := _SESSIONS_RE.search(cleaned):
            raw = match.group("count").lower()
            sessions = _WORD_NUMBERS.get(raw) or int(raw)
            sessions = sessions if 1 <= sessions <= 14 else None

        summary = cleaned if len(cleaned) <= 120 else cleaned[:117].rstrip() + "..."
        return FitnessGoal(
            goal_type=goal_type,
            target=target,
            timeframe=timeframe,
            sessions_per_week=sessions,
            summary=summary,
            source=self.name,
        )


class ClaudeGoalParser:
    """Ask Claude for the same JSON shape; fall back to rules on any problem.

    The fallback is not defensive decoration — it is the contract. A missing
    key, a network failure, a rate limit or a non-JSON reply must all degrade to
    the rule-based result rather than failing a sign-up.
    """

    name = "claude"

    def __init__(
        self,
        *,
        client=None,
        model: str | None = None,
        fallback: GoalParser | None = None,
    ) -> None:
        self._client = client
        self._model = model or settings.AI_MODEL
        self._fallback = fallback or RuleBasedGoalParser()

    @property
    def client(self):
        if self._client is None:
            import anthropic  # imported lazily: an optional dependency

            self._client = anthropic.Anthropic()
        return self._client

    def parse(self, text: str) -> FitnessGoal:
        cleaned = (text or "").strip()
        if not cleaned:
            return self._fallback.parse(cleaned)
        try:
            response = self.client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": cleaned}],
            )
            payload = self._extract_json(response)
            return self._to_goal(payload, cleaned)
        except Exception:
            logger.warning("Claude goal parsing failed; using rule-based parser", exc_info=True)
            return self._fallback.parse(cleaned)

    @staticmethod
    def _extract_json(response) -> dict:
        text = "".join(
            block.text for block in response.content if getattr(block, "type", "") == "text"
        ).strip()
        # Tolerate a fenced block without making the prompt more fragile.
        if text.startswith("```"):
            text = text.split("```")[1].removeprefix("json").strip()
        return json.loads(text)

    def _to_goal(self, payload: dict, original: str) -> FitnessGoal:
        goal_type = payload.get("goal_type")
        if goal_type not in GOAL_TYPES:
            goal_type = "general_fitness"
        sessions = payload.get("sessions_per_week")
        try:
            sessions = int(sessions) if sessions is not None else None
        except (TypeError, ValueError):
            sessions = None
        if sessions is not None and not 1 <= sessions <= 14:
            sessions = None
        summary = (payload.get("summary") or original)[:120]
        return FitnessGoal(
            goal_type=goal_type,
            target=_clean_optional(payload.get("target")),
            timeframe=_clean_optional(payload.get("timeframe")),
            sessions_per_week=sessions,
            summary=summary,
            source=self.name,
        )


def _clean_optional(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:80] or None


_PARSERS: dict[str, type] = {
    RuleBasedGoalParser.name: RuleBasedGoalParser,
    ClaudeGoalParser.name: ClaudeGoalParser,
}


def get_goal_parser() -> GoalParser:
    """Return the configured parser, degrading to rules whenever Claude cannot run."""
    requested = (settings.AI_GOAL_PARSER or "rules").lower()
    if requested != ClaudeGoalParser.name:
        return RuleBasedGoalParser()
    if not settings.ANTHROPIC_API_KEY:
        logger.info("AI_GOAL_PARSER=claude but no ANTHROPIC_API_KEY is set; using rules")
        return RuleBasedGoalParser()
    try:
        import anthropic  # noqa: F401
    except ImportError:
        logger.info("AI_GOAL_PARSER=claude but the anthropic package is missing; using rules")
        return RuleBasedGoalParser()
    return ClaudeGoalParser()
