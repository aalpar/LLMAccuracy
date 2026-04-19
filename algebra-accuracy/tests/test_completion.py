"""Tests for the completion-status enum in evaluate.py results."""
from evaluate import classify_completion


def test_end_turn_is_completion_end_turn():
    assert classify_completion(
        stop_reason="end_turn",
        budget_hit=False,
        rounds_hit=False,
    ) == "end_turn"


def test_max_tokens_is_completion_max_tokens():
    assert classify_completion(
        stop_reason="max_tokens",
        budget_hit=False,
        rounds_hit=False,
    ) == "max_tokens"


def test_budget_hit_is_completion_budget_exhausted():
    assert classify_completion(
        stop_reason="tool_use",
        budget_hit=True,
        rounds_hit=False,
    ) == "budget_exhausted"


def test_rounds_hit_is_completion_max_rounds():
    assert classify_completion(
        stop_reason="tool_use",
        budget_hit=False,
        rounds_hit=True,
    ) == "max_rounds"


def test_budget_beats_rounds_when_both_hit():
    """Budget exhaustion is detected before round loop re-enters; prefer it."""
    assert classify_completion(
        stop_reason="tool_use",
        budget_hit=True,
        rounds_hit=True,
    ) == "budget_exhausted"
