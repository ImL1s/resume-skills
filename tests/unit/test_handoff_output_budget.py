"""#63: handoff uses explicit serialized-output budget, not recovered-content alone."""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from portable_resume.bounds import DEFAULT_BOUNDS
from portable_resume import handoff
from portable_resume.handoff import (
    CHECKLIST,
    UNTRUSTED_BANNER,
    render_handoff,
    render_session,
)
from portable_resume.diagnostics import WARNING_CODES
from portable_resume.model import Envelope, Query, Session, Turn


class HandoffOutputBudgetTests(unittest.TestCase):
    def _session(
        self,
        *,
        user: str,
        assistant: str = "ok",
        turns: tuple[Turn, ...] = (),
        session_id: str = "sess-1",
    ) -> Session:
        return Session(
            source="claude",
            session_id=session_id,
            title="t",
            cwd="/tmp/project",
            branch="main",
            last_user_request=user,
            last_assistant_action=assistant,
            turns=turns,
        )

    def test_handoff_output_ceiling_is_distinct_from_normalized_content(self) -> None:
        self.assertGreater(DEFAULT_BOUNDS.handoff_output_bytes, DEFAULT_BOUNDS.normalized_content_bytes)

    def test_content_at_normalized_ceiling_still_renders_handoff(self) -> None:
        # Recovered content at the normalized ceiling must not fail solely because
        # Markdown framing adds wrapper bytes (#63).
        payload = "x" * DEFAULT_BOUNDS.normalized_content_bytes
        session = self._session(user=payload)
        # sanitize_session would truncate; here we feed an already-large Session
        # that models the boundary case the renderer must handle.
        rendered = render_session(session)
        self.assertIn(UNTRUSTED_BANNER, rendered)
        for item in CHECKLIST:
            self.assertIn(item, rendered)
        self.assertLessEqual(len(rendered.encode("utf-8")), DEFAULT_BOUNDS.handoff_output_bytes)
        # Either full content or explicit truncation — never bare E_LIMIT_EXCEEDED.
        self.assertTrue("x" in rendered or "W_TRUNCATED" in rendered)

    def test_newline_heavy_content_stays_within_handoff_budget(self) -> None:
        # Each line gains "> " prefix; must not exceed handoff_output_bytes.
        lines = ["line"] * 200_000
        text = "\n".join(lines)
        session = self._session(user=text[: DEFAULT_BOUNDS.normalized_content_bytes])
        rendered = render_session(session)
        self.assertLessEqual(len(rendered.encode("utf-8")), DEFAULT_BOUNDS.handoff_output_bytes)
        self.assertIn(UNTRUSTED_BANNER, rendered)
        self.assertIn(CHECKLIST[0], rendered)

    def test_truncation_preserves_security_framing_and_marks_warning(self) -> None:
        # Force truncation by using huge user + many turns.
        user = ("U" * 100_000 + "\n") * 100
        turns = tuple(
            Turn(ordinal=i, role="assistant" if i % 2 else "user", content=("T" * 50_000 + "\n") * 20)
            for i in range(40)
        )
        session = self._session(user=user, assistant="A" * 200_000, turns=turns)
        rendered = render_session(session)
        self.assertIn(UNTRUSTED_BANNER, rendered)
        for item in CHECKLIST:
            self.assertIn(item, rendered)
        self.assertIn("W_TRUNCATED", rendered)
        self.assertLessEqual(len(rendered.encode("utf-8")), DEFAULT_BOUNDS.handoff_output_bytes)

    def test_utf8_multibyte_not_split(self) -> None:
        # Prefer CJK so any naive byte slice would break decode if buggy.
        chunk = "你好" * 100_000
        session = self._session(user=chunk)
        rendered = render_session(session)
        rendered.encode("utf-8").decode("utf-8")
        self.assertIn(UNTRUSTED_BANNER, rendered)

    def test_repeat_render_byte_identical(self) -> None:
        session = self._session(user="hello\nworld", assistant="done")
        envelope = Envelope.create(
            operation="show",
            query=Query("claude", cwd="/tmp/project"),
            sessions=(session,),
            generated_at="2026-07-20T00:00:00Z",
        )
        self.assertEqual(render_handoff(envelope), render_handoff(envelope))

    def test_drops_oldest_turns_before_latest_user_request(self) -> None:
        turns = tuple(Turn(ordinal=i, role="user", content=f"old-{i}-" + ("z" * 20_000)) for i in range(30))
        session = self._session(user="LATEST_USER_MARKER", assistant="LATEST_ASSISTANT", turns=turns)
        rendered = render_session(session)
        self.assertIn("LATEST_USER_MARKER", rendered)
        self.assertIn(UNTRUSTED_BANNER, rendered)

    def test_dropped_turn_count_is_announced_at_evidence_cut_point(self) -> None:
        turns = tuple(
            Turn(ordinal=i, role="user", content=f"turn-{i}-" + ("z" * 600))
            for i in range(8)
        )
        session = self._session(
            user="LATEST_USER", assistant="LATEST_ASSISTANT", turns=turns
        )
        bounds = replace(DEFAULT_BOUNDS, handoff_output_bytes=3_500)

        with patch("portable_resume.handoff.DEFAULT_BOUNDS", bounds):
            rendered = render_session(session)

        kept_ordinals = [i for i in range(8) if f"> **[{i} user]**" in rendered]
        self.assertGreater(len(kept_ordinals), 0)
        self.assertLess(len(kept_ordinals), len(turns))
        omitted = len(turns) - len(kept_ordinals)
        cut_notice = f"> _({omitted} earlier turns omitted to fit the output budget; newest turns kept)_"
        evidence = rendered.index("### Bounded transcript evidence")
        first_turn = rendered.index(f"> **[{kept_ordinals[0]} user]**")
        self.assertIn(cut_notice, rendered[evidence:first_turn])
        self.assertIn(
            "`[W_TRUNCATED]` earlier transcript turns were omitted to fit the output budget.",
            rendered,
        )

    def test_turn_body_truncation_has_distinct_warning_notice(self) -> None:
        session = self._session(
            user="LATEST_USER",
            turns=(Turn(ordinal=0, role="user", content="shortened", truncated=True),),
        )

        rendered = render_session(session)

        self.assertIn(
            "`[W_TRUNCATED]` one or more recovered text bodies were shortened before display.",
            rendered,
        )
        self.assertNotIn("earlier transcript turns were omitted", rendered)

    def test_every_handoff_warning_has_a_static_explanation(self) -> None:
        install_only = {
            "W_HOST_DISCOVERY_UNPROVEN",
            "W_LIVE_SMOKE_NOT_RUN",
            "W_SKILL_DUPLICATE",
            "W_SKILL_SHADOW",
        }
        explanations = getattr(handoff, "HANDOFF_WARNING_EXPLANATIONS", {})
        self.assertEqual(set(WARNING_CODES) - install_only, set(explanations))
        self.assertTrue(
            all(value and "\n" not in value for value in explanations.values())
        )

    def test_many_turns_fit_without_quadratic_stall(self) -> None:
        # Codex P1: one-turn-at-a-time rebuild stalled on ~2k newline-heavy turns.
        turns = tuple(Turn(ordinal=i, role="user", content=("x\n" * 80)) for i in range(2_000))
        session = self._session(user="USER", assistant="ASSIST", turns=turns)
        rendered = render_session(session)
        self.assertLessEqual(len(rendered.encode("utf-8")), DEFAULT_BOUNDS.handoff_output_bytes)
        self.assertIn(UNTRUSTED_BANNER, rendered)
        self.assertIn("USER", rendered)

    def test_envelope_warnings_generator_not_exhausted_on_retry(self) -> None:
        session = self._session(user="y" * 500_000, assistant="z" * 500_000)
        # Force truncation path so assemble runs more than once.
        def warnings() -> Iterable[str]:
            yield "W_STALE_INDEX"

        from typing import Iterable

        rendered = render_session(session, envelope_warnings=warnings())
        self.assertIn("W_STALE_INDEX", rendered)


if __name__ == "__main__":
    unittest.main()
