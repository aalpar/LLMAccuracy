"""Unit tests for capability-map generators.

Each test verifies that a generator produces well-formed Problem
dataclasses at the requested count and difficulty. Integration with
Wile (actually running the scheme_expression) is a separate smoke test.
"""
import random
from generate_capability_problems import (
    gen_graph_reachability,
    gen_set_closure,
)


def test_graph_reachability_produces_requested_count():
    random.seed(0)
    problems = gen_graph_reachability("easy", n=3)
    assert len(problems) == 3


def test_graph_reachability_problem_has_required_fields():
    random.seed(0)
    p = gen_graph_reachability("medium", n=1)[0]
    assert p.category == "graph_reachability"
    assert p.difficulty == "medium"
    assert p.id.startswith("reach-medium-")
    assert p.answer_type == "set"
    assert "reach" in p.natural_language.lower() or "reachable" in p.natural_language.lower()
    assert p.scheme_expression  # non-empty


def test_graph_reachability_supports_three_difficulties():
    random.seed(0)
    for diff in ("easy", "medium", "hard"):
        problems = gen_graph_reachability(diff, n=1)
        assert len(problems) == 1
        assert problems[0].difficulty == diff


def test_set_closure_produces_requested_count():
    random.seed(0)
    problems = gen_set_closure("easy", n=3)
    assert len(problems) == 3


def test_set_closure_problem_has_required_fields():
    random.seed(0)
    p = gen_set_closure("medium", n=1)[0]
    assert p.category == "set_closure"
    assert p.difficulty == "medium"
    assert p.id.startswith("closure-medium-")
    assert p.answer_type == "set"


def test_set_closure_supports_three_difficulties():
    random.seed(0)
    for diff in ("easy", "medium", "hard"):
        problems = gen_set_closure(diff, n=1)
        assert problems[0].difficulty == diff
