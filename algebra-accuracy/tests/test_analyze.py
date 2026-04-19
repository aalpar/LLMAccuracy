"""Tests for the cell classifier in analyze_gradient_results.py."""
from analyze_gradient_results import classify, summarize_cell


def _mk_sample(ctrl_correct, treat_correct, ctrl_completion="end_turn",
               treat_completion="end_turn", ctrl_tok=1000, treat_tok=1000):
    """Construct a single-problem sample dict matching results-v3 schema."""
    return {
        "control_correct": ctrl_correct,
        "treatment_correct": treat_correct,
        "control": {
            "completion": ctrl_completion,
            "truncated": ctrl_completion != "end_turn",
            "output_tokens": ctrl_tok,
        },
        "treatment": {
            "completion": treat_completion,
            "truncated": treat_completion != "end_turn",
            "output_tokens": treat_tok,
        },
    }


def test_classify_trivial():
    # 10/10 control correct → TRIVIAL
    samples = [_mk_sample(True, True) for _ in range(10)]
    s = summarize_cell(samples)
    assert s["classification"] == "TRIVIAL"


def test_classify_calibrated():
    # 5/10 control correct → in the 30-70% band → CALIBRATED
    samples = [_mk_sample(True, True) for _ in range(5)] + \
              [_mk_sample(False, False) for _ in range(5)]
    s = summarize_cell(samples)
    assert s["classification"] == "CALIBRATED"


def test_classify_budget_bound():
    # 0/10 control correct, all failures are budget_exhausted
    samples = [_mk_sample(False, False, ctrl_completion="budget_exhausted")
               for _ in range(10)]
    s = summarize_cell(samples)
    assert s["classification"] == "BUDGET-BOUND"


def test_classify_round_capped():
    # 0/10 control correct, all failures are max_rounds
    samples = [_mk_sample(False, False, ctrl_completion="max_rounds")
               for _ in range(10)]
    s = summarize_cell(samples)
    assert s["classification"] == "ROUND-CAPPED"


def test_classify_mixed():
    # 20% control correct — below calibrated band, above zero, not all truncated
    samples = [_mk_sample(True, True) for _ in range(2)] + \
              [_mk_sample(False, False, ctrl_completion="end_turn") for _ in range(8)]
    s = summarize_cell(samples)
    assert s["classification"] == "MIXED"


def test_summarize_cell_tracks_completion_rates():
    samples = [_mk_sample(True, True) for _ in range(5)] + \
              [_mk_sample(False, False, treat_completion="max_rounds") for _ in range(5)]
    s = summarize_cell(samples)
    assert s["treat_completion_counts"]["end_turn"] == 5
    assert s["treat_completion_counts"]["max_rounds"] == 5
