"""Integration test for run_treatment completion detection.

Uses a minimal mock client that returns scripted responses. Verifies the
completion field correctly identifies each terminal state.
"""
import pytest
from unittest.mock import MagicMock
from evaluate import run_treatment


def _mock_response(text="", stop_reason="end_turn", tool_use=False, in_tok=100, out_tok=50):
    resp = MagicMock()
    resp.stop_reason = stop_reason
    resp.usage.input_tokens = in_tok
    resp.usage.output_tokens = out_tok
    resp.usage.cache_creation_input_tokens = 0
    resp.usage.cache_read_input_tokens = 0

    blocks = []
    if text:
        text_block = MagicMock()
        text_block.text = text
        text_block.type = "text"
        blocks.append(text_block)
    if tool_use:
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = "eval"
        tool_block.input = {"code": "(+ 1 1)"}
        tool_block.id = "tool_1"
        # Remove the auto-created .text attribute so hasattr() returns False
        del tool_block.text
        blocks.append(tool_block)
    resp.content = blocks
    return resp


class FakeMCP:
    def call_tool(self, name, args):
        return "2"

    def reset(self):
        pass


def test_end_turn_completion():
    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        text="ANSWER: 2", stop_reason="end_turn"
    )
    problem = {"natural_language": "what is 1+1"}
    result = run_treatment(
        client, "fake-model", problem, FakeMCP(), tools=[],
        total_budget=5000, per_round_cap=5000,
    )
    assert result["completion"] == "end_turn"
    assert result["truncated"] is False


def test_max_rounds_completion():
    """Model keeps calling tools past max_rounds — harness cuts it off."""
    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        stop_reason="tool_use", tool_use=True, out_tok=100,
    )
    problem = {"natural_language": "unbounded"}
    result = run_treatment(
        client, "fake-model", problem, FakeMCP(), tools=[],
        total_budget=100_000, per_round_cap=5000, max_rounds=3,
    )
    assert result["completion"] == "max_rounds"
    assert result["truncated"] is True
    assert result["rounds"] == 3


def test_budget_exhausted_completion():
    """Cumulative output_tokens exceeds total_budget before conversation ends."""
    client = MagicMock()
    client.messages.create.return_value = _mock_response(
        stop_reason="tool_use", tool_use=True, out_tok=500,
    )
    problem = {"natural_language": "expensive"}
    result = run_treatment(
        client, "fake-model", problem, FakeMCP(), tools=[],
        total_budget=800, per_round_cap=5000, max_rounds=100,
    )
    assert result["completion"] == "budget_exhausted"
    assert result["truncated"] is True
