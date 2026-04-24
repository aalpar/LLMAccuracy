# Calibrated-Cells Re-Run at n=30 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce statistically-honest measurements of treatment vs. control deltas on the 3 CALIBRATED cells (`powerset_lattice/medium`, `powerset_lattice/hard`, `tropical_semiring/hard`) by (a) removing the round-cap confound, (b) parallelizing the harness, and (c) running at n=30.

**Architecture:** Three coupled changes. First, the harness (`evaluate.py`) gains a configurable `max_rounds` CLI option and replaces its imprecise `truncated` boolean with a `completion` enum `{end_turn, max_tokens, max_rounds, budget_exhausted}` so the analyzer can distinguish token exhaustion from round exhaustion. Second, the analyzer (`analyze_gradient_results.py`) is updated to classify cells using the new field, including a new `ROUND-CAPPED` class. Third, `evaluate.py`'s main evaluation loop is converted from serial to parallel via `asyncio` with one `WileMCPSession` subprocess per worker. Then we generate 90 fresh problems (3 cells × n=30) with a new seed, run the expanded benchmark, and analyze.

**Tech Stack:** Python 3.10, `anthropic` SDK 0.86 (supports `AsyncAnthropic`), `asyncio`, `pytest` (new, for harness tests), Wile MCP stdio subprocess.

---

## Pre-flight

**Context to understand before starting:**
- `evaluate.py:349-453` — current `run_treatment`, including the hard-coded `max_rounds = 10` (line 366) that caused 9/10 `powerset_lattice/hard` treatment failures in `gradient_results_alpha.json`.
- `evaluate.py:438` — current `truncated` logic: `budget_hit or last_stop_reason == "max_tokens"`. Does NOT mark `stop_reason == "tool_use"` (round cap hit) as truncated. This is the bug that hid the confound.
- `analyze_gradient_results.py:32-40` — classification logic reading `truncated`. Will need to read `completion` instead.
- `gradient_results_alpha.json` — results file showing 9/10 powerset_lattice/hard treatment runs ended with `stop_reason=tool_use, rounds=10, truncated=False`.
- `generate.py:586-620, 231-316` — generators for `powerset_lattice` and `tropical_semiring`. Problem IDs are `{prefix}-{difficulty}-{i:03d}`; regenerating with same seed overwrites.

**Working assumption:** The existing 90 problems in `gradient_problems_v2.json` stay untouched. We generate a separate 90-problem file (`gradient_problems_n30.json`) for the 3 CALIBRATED cells at n=30 using a fresh seed (2026), to keep this experiment independent of the alpha run.

---

## Task 0: Create branch and test scaffolding

**Files:**
- Create: `algebra-accuracy/tests/__init__.py` (empty)
- Create: `algebra-accuracy/tests/conftest.py`
- Create: `algebra-accuracy/pytest.ini`

- [ ] **Step 1: Create feature branch**

```bash
cd /Users/aalpar/ClaudeProjects/LLMAccuracy
git checkout -b calibrated-cells-n30
```

Expected: `Switched to a new branch 'calibrated-cells-n30'`

- [ ] **Step 2: Create pytest config**

Create `algebra-accuracy/pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

- [ ] **Step 3: Create empty test package**

```bash
mkdir -p algebra-accuracy/tests
touch algebra-accuracy/tests/__init__.py
```

Create `algebra-accuracy/tests/conftest.py`:

```python
"""Pytest fixtures shared across harness tests."""
import sys
from pathlib import Path

# Make algebra-accuracy/ importable as a package root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

- [ ] **Step 4: Verify pytest discovers the tests dir**

```bash
cd algebra-accuracy && python3 -m pytest --collect-only 2>&1 | head
```

Expected: `no tests ran` or `collected 0 items` (no error).

- [ ] **Step 5: Commit scaffolding**

```bash
git add algebra-accuracy/tests/ algebra-accuracy/pytest.ini
git commit -m "test: scaffold pytest infrastructure for harness"
```

---

## Task 1: Replace `truncated` with `completion` enum

**Context:** Current `truncated` boolean collapses three distinct failure modes (max_tokens, budget_exhausted, round_cap) with `end_turn`. We need a four-way enum to distinguish them so the analyzer can classify `powerset_lattice/hard` failures as round-cap rather than mystery-mixed.

**Files:**
- Modify: `algebra-accuracy/evaluate.py:321-346` (`run_control`)
- Modify: `algebra-accuracy/evaluate.py:349-453` (`run_treatment`)
- Modify: `algebra-accuracy/evaluate.py:580-616` (`run_control_session`)
- Modify: `algebra-accuracy/evaluate.py:619-721` (`run_treatment_session`)
- Create: `algebra-accuracy/tests/test_completion.py`

- [ ] **Step 1: Write failing tests for completion enum**

Create `algebra-accuracy/tests/test_completion.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd algebra-accuracy && python3 -m pytest tests/test_completion.py -v
```

Expected: `ImportError` on `classify_completion` (function doesn't exist yet).

- [ ] **Step 3: Add `classify_completion` to evaluate.py**

Add after line 316 (after `answers_match`, before `# ── Evaluation Loop ──`):

```python
# ── Completion Status ────────────────────────────────────────────
#
# The Anthropic API's `stop_reason` alone doesn't capture why a tool-using
# run ended. `stop_reason == "tool_use"` means the model wanted another
# tool call — but whether the harness allowed it depends on our budget
# and round caps. We enumerate four terminal states:
#
#   end_turn            — model produced final answer cleanly
#   max_tokens          — final API call hit the per-call token cap
#   budget_exhausted    — cumulative output_tokens reached total_budget
#   max_rounds          — treatment loop hit max_rounds with tool_use pending

COMPLETION_STATES = ("end_turn", "max_tokens", "budget_exhausted", "max_rounds")


def classify_completion(stop_reason: str, budget_hit: bool, rounds_hit: bool) -> str:
    """Classify the terminal state of an evaluation run.

    Precedence when multiple apply:
      budget_exhausted > max_rounds > max_tokens > end_turn

    Budget exhaustion is the hardest cap — it's checked before the loop
    re-enters — so if it fires alongside rounds_hit, budget wins. max_tokens
    is per-call and only matters if nothing more global fired.
    """
    if budget_hit:
        return "budget_exhausted"
    if rounds_hit:
        return "max_rounds"
    if stop_reason == "max_tokens":
        return "max_tokens"
    return "end_turn"
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd algebra-accuracy && python3 -m pytest tests/test_completion.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Integrate `classify_completion` into `run_control`**

Modify `run_control` (currently lines 321-346). Replace the final `return` dict with:

```python
    elapsed = time.perf_counter() - t0
    text = "".join(b.text for b in response.content if hasattr(b, "text"))
    completion = classify_completion(
        stop_reason=response.stop_reason,
        budget_hit=False,
        rounds_hit=False,
    )
    return {
        "raw_response": text,
        "extracted_answer": extract_answer(text),
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "stop_reason": response.stop_reason,
        "completion": completion,
        "truncated": completion != "end_turn",
        "total_budget": max_tokens,
        "elapsed_s": round(elapsed, 3),
    }
```

(We keep `truncated` as a derived field so any external tooling that still reads it continues to work.)

- [ ] **Step 6: Integrate `classify_completion` into `run_treatment`**

Modify `run_treatment` (currently lines 349-453). Need to track whether the round cap was hit. Add `rounds_hit` tracking:

Replace the `for _ in range(max_rounds):` loop through the end of the function with:

```python
    rounds_hit = False
    t0 = time.perf_counter()
    for round_i in range(max_rounds):
        remaining = total_budget - total_output_tokens
        if remaining <= 0:
            budget_hit = True
            break
        this_cap = max(1, min(per_round_cap, remaining))

        response = client.messages.create(
            model=model,
            max_tokens=this_cap,
            system=cached_system,
            messages=messages,
            tools=tools,
        )
        rounds += 1
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens
        total_cache_creation_tokens += getattr(response.usage, "cache_creation_input_tokens", 0)
        total_cache_read_tokens += getattr(response.usage, "cache_read_input_tokens", 0)
        last_stop_reason = response.stop_reason

        tool_uses = []
        for block in response.content:
            if hasattr(block, "text"):
                full_text += block.text
            if block.type == "tool_use":
                tool_uses.append(block)

        if not tool_uses:
            break

        tool_calls += len(tool_uses)

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in tool_uses:
            result = mcp_session.call_tool(block.name, block.input)
            tool_trace.append({
                "tool": block.name,
                "arguments": block.input,
                "output": result,
            })
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                }
            )
        messages.append({"role": "user", "content": tool_results})

        if response.stop_reason == "end_turn":
            break
    else:
        # for-else: executed only if the loop didn't break. We exhausted
        # max_rounds iterations with the model still wanting tool use.
        if last_stop_reason == "tool_use":
            rounds_hit = True

    elapsed = time.perf_counter() - t0
    completion = classify_completion(
        stop_reason=last_stop_reason,
        budget_hit=budget_hit,
        rounds_hit=rounds_hit,
    )
    return {
        "raw_response": full_text,
        "extracted_answer": extract_answer(full_text),
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cache_creation_tokens": total_cache_creation_tokens,
        "cache_read_tokens": total_cache_read_tokens,
        "stop_reason": last_stop_reason,
        "completion": completion,
        "truncated": completion != "end_turn",
        "total_budget": total_budget,
        "elapsed_s": round(elapsed, 3),
        "rounds": rounds,
        "tool_calls": tool_calls,
        "tool_trace": tool_trace,
    }
```

Note the Python `for/else`: the `else` clause runs only when the for loop completes all iterations without `break`. That's exactly the condition for round-cap exhaustion.

- [ ] **Step 7: Apply the same changes to `run_control_session` and `run_treatment_session`**

Session-mode counterparts (lines 580-616 and 619-721) have the same structure. Apply identical edits: track `rounds_hit`, call `classify_completion`, add `completion` field to the result dict, keep `truncated` as derived.

- [ ] **Step 8: Write an integration test stub for run_treatment completion**

Create `algebra-accuracy/tests/test_run_treatment.py`:

```python
"""Integration test for run_treatment completion detection.

Uses a minimal mock client that returns scripted responses. Verifies the
completion field correctly identifies each terminal state.
"""
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
        # Give the block a .text attribute (hasattr check in run_treatment)
        # but MagicMock default .text would pass hasattr; force it to only
        # expose text when we want. Use spec to constrain.
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
        total_budget=5000, per_round_cap=5000, max_rounds=10,
    )
    assert result["completion"] == "end_turn"
    assert result["truncated"] is False


def test_max_rounds_completion():
    """Model keeps calling tools past max_rounds — harness cuts it off."""
    client = MagicMock()
    # Every call requests another tool_use; never converges.
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
```

Note: `run_treatment` currently doesn't accept `max_rounds` as a parameter — Task 2 adds it.

- [ ] **Step 9: Skip the max_rounds test for now (Task 2 adds the parameter)**

Mark `test_max_rounds_completion` with `@pytest.mark.skip(reason="max_rounds param added in Task 2")` for now. Also skip `test_budget_exhausted_completion` since it depends on the same parameter signature.

Add `import pytest` at the top.

- [ ] **Step 10: Run the test suite — only end_turn test should pass**

```bash
cd algebra-accuracy && python3 -m pytest tests/ -v
```

Expected: `test_end_turn_completion` passes; 2 tests skipped; 5 `test_completion.py` tests pass.

- [ ] **Step 11: Commit**

```bash
git add algebra-accuracy/evaluate.py algebra-accuracy/tests/
git commit -m "feat(harness): add completion enum for terminal-state classification

Replaces the imprecise 'truncated' boolean with a four-way 'completion'
enum: end_turn, max_tokens, max_rounds, budget_exhausted. Previously,
run_treatment silently lumped round-cap exhaustion with end_turn (setting
truncated=False), hiding the round-cap confound that dominated failures
in gradient_results_alpha.json. 'truncated' remains as a derived field
(completion != end_turn) for backward compat."
```

---

## Task 2: Make `max_rounds` a CLI parameter

**Context:** `run_treatment` hard-codes `max_rounds = 10` on line 366. The `powerset_lattice/hard` alpha results show 9/10 treatment runs hitting this cap. It must be configurable and have a sensible higher default (30).

**Files:**
- Modify: `algebra-accuracy/evaluate.py` (signatures + argparse + call sites)

- [ ] **Step 1: Add `max_rounds` parameter to `run_treatment`**

Change the signature (currently line 349):

```python
def run_treatment(
    client,
    model,
    problem,
    mcp_session,
    tools,
    total_budget=5000,
    per_round_cap=5000,
    max_rounds=30,
):
```

Remove the inner `max_rounds = 10` assignment.

- [ ] **Step 2: Add `max_rounds` to `run_treatment_session`**

Same change for `run_treatment_session` (line 619). Replace the literal `range(10)` on line 650 with `range(max_rounds)`.

- [ ] **Step 3: Add `--max-rounds` CLI argument**

In `main()` around line 768 (after the `--total-budget` block), add:

```python
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=30,
        help=(
            "Maximum number of tool-calling rounds in treatment per problem. "
            "Default 30 (up from previous hard-coded 10). Round cap is a "
            "common failure mode for lattice-problem reasoning; raising it "
            "lets the model iterate helper functions to convergence."
        ),
    )
```

- [ ] **Step 4: Plumb `max_rounds` through call sites**

Two call sites:

1. `run_treatment(...)` on line 897 — add `max_rounds=args.max_rounds`.
2. `run_treatment_session(...)` on line 868 — add `max_rounds=args.max_rounds`.

- [ ] **Step 5: Un-skip and run the max_rounds and budget_exhausted tests**

Remove the `@pytest.mark.skip` decorators from `test_max_rounds_completion` and `test_budget_exhausted_completion` in `tests/test_run_treatment.py`.

```bash
cd algebra-accuracy && python3 -m pytest tests/test_run_treatment.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 6: Sanity-check the CLI**

```bash
cd algebra-accuracy && python3 evaluate.py --help 2>&1 | grep -A2 max-rounds
```

Expected: the `--max-rounds` help block appears with default 30.

- [ ] **Step 7: Commit**

```bash
git add algebra-accuracy/evaluate.py algebra-accuracy/tests/test_run_treatment.py
git commit -m "feat(harness): expose max_rounds as --max-rounds CLI option (default 30)

Previously hard-coded to 10 in run_treatment. The alpha run showed this
was the dominant failure mode for powerset_lattice/hard (9/10 treatment
failures hit round cap with output_tokens well under budget). Default
raised to 30; configurable per run."
```

---

## Task 3: Update `analyze_gradient_results.py` to use `completion`

**Context:** The analyzer currently reads `truncated` (evaluate.py's imprecise flag). It should read `completion` to distinguish budget-bound cells from round-capped cells, and add per-cell completion-state breakdown.

**Files:**
- Modify: `algebra-accuracy/analyze_gradient_results.py`
- Create: `algebra-accuracy/tests/test_analyze.py`

- [ ] **Step 1: Write failing tests for the analyzer**

Create `algebra-accuracy/tests/test_analyze.py`:

```python
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
```

- [ ] **Step 2: Run tests to confirm failures**

```bash
cd algebra-accuracy && python3 -m pytest tests/test_analyze.py -v
```

Expected: tests fail (missing `ROUND-CAPPED` class, missing `treat_completion_counts` field).

- [ ] **Step 3: Update `classify` signature and logic**

Replace `analyze_gradient_results.py:32-40` with:

```python
def classify(
    control_rate: float,
    all_failures_budget: bool,
    all_failures_rounds: bool,
) -> str:
    """Label a cell by its control-arm behavior.

    A cell is:
      TRIVIAL       — control ≥ 95%: tier is too easy, not discriminative
      BUDGET-BOUND  — control = 0% and all failures hit budget_exhausted
      ROUND-CAPPED  — control = 0% and all failures hit max_rounds
      CALIBRATED    — control 30–70%: sweet spot for tool advantage
      MIXED         — anything else: informative but not pure signal
    """
    if control_rate >= 0.95:
        return "TRIVIAL"
    if control_rate == 0.0:
        if all_failures_budget:
            return "BUDGET-BOUND"
        if all_failures_rounds:
            return "ROUND-CAPPED"
    if 0.30 <= control_rate <= 0.70:
        return "CALIBRATED"
    return "MIXED"
```

- [ ] **Step 4: Update `summarize_cell` to compute completion rates**

Replace `analyze_gradient_results.py:43-85` with:

```python
from collections import Counter


def _completion_counts(samples, arm):
    """Count completion-state occurrences for one arm across a cell."""
    c = Counter()
    for s in samples:
        if arm in s:
            c[s[arm].get("completion", "unknown")] += 1
    return dict(c)


def summarize_cell(samples):
    """Aggregate per-problem samples into cell-level statistics."""
    n = len(samples)
    ctrl_correct = sum(1 for s in samples if s.get("control_correct"))
    treat_correct = sum(1 for s in samples if s.get("treatment_correct"))

    ctrl_counts = _completion_counts(samples, "control")
    treat_counts = _completion_counts(samples, "treatment")

    # Failure-mode attribution for the control arm
    ctrl_failures = [
        s for s in samples
        if not s.get("control_correct") and "control" in s
    ]
    n_ctrl_fail = len(ctrl_failures)
    n_ctrl_budget = sum(
        1 for s in ctrl_failures
        if s["control"].get("completion") == "budget_exhausted"
    )
    n_ctrl_rounds = sum(
        1 for s in ctrl_failures
        if s["control"].get("completion") == "max_rounds"
    )
    all_failures_budget = n_ctrl_fail > 0 and n_ctrl_budget == n_ctrl_fail
    all_failures_rounds = n_ctrl_fail > 0 and n_ctrl_rounds == n_ctrl_fail

    ctrl_truncated = sum(
        1 for s in samples
        if "control" in s
        and s["control"].get("completion", "end_turn") != "end_turn"
    )
    treat_truncated = sum(
        1 for s in samples
        if "treatment" in s
        and s["treatment"].get("completion", "end_turn") != "end_turn"
    )
    treat_rounds_hit = sum(
        1 for s in samples
        if "treatment" in s
        and s["treatment"].get("completion") == "max_rounds"
    )
    treat_tokens = [
        s["treatment"]["output_tokens"]
        for s in samples if "treatment" in s
    ]
    ctrl_tokens = [
        s["control"]["output_tokens"]
        for s in samples if "control" in s
    ]

    ctrl_rate = ctrl_correct / n if n else 0.0
    return {
        "n": n,
        "ctrl_rate": ctrl_rate,
        "treat_rate": treat_correct / n if n else 0.0,
        "ctrl_truncated_rate": ctrl_truncated / n if n else 0.0,
        "treat_truncated_rate": treat_truncated / n if n else 0.0,
        "treat_rounds_hit_rate": treat_rounds_hit / n if n else 0.0,
        "ctrl_median_tokens": int(statistics.median(ctrl_tokens)) if ctrl_tokens else 0,
        "treat_median_tokens": int(statistics.median(treat_tokens)) if treat_tokens else 0,
        "ctrl_completion_counts": ctrl_counts,
        "treat_completion_counts": treat_counts,
        "classification": classify(ctrl_rate, all_failures_budget, all_failures_rounds),
    }
```

- [ ] **Step 5: Update the report table in `main()` to show round-cap rate**

Modify `analyze_gradient_results.py:107-131`. Add a `TreatRd` column showing treatment round-cap rate:

```python
    print(f"{'Category':<20} {'Difficulty':<12} {'n':>3}  "
          f"{'Ctrl':>6} {'Treat':>6} {'Δ':>6}  "
          f"{'CtrlTrunc':>10} {'TreatRd':>8} {'CtrlMed':>8} {'TreatMed':>9}  "
          f"{'Classification':<14}")
    print("-" * 115)
```

And update the per-row print:

```python
            print(
                f"{cat:<20} {diff:<12} {s['n']:>3}  "
                f"{s['ctrl_rate']:>5.0%} {s['treat_rate']:>5.0%} {delta:>+5.0%}  "
                f"{s['ctrl_truncated_rate']:>9.0%} {s['treat_rounds_hit_rate']:>7.0%} "
                f"{s['ctrl_median_tokens']:>8} {s['treat_median_tokens']:>9}  "
                f"{s['classification']:<14}"
            )
```

- [ ] **Step 6: Update the regeneration-targets block**

Replace `analyze_gradient_results.py:140-155` with:

```python
    # Regeneration suggestions
    print("── Regeneration targets ──")
    trivial = []
    budget = []
    rounds = []
    for (cat, diff), samples in cells.items():
        s = summarize_cell(samples)
        if s["classification"] == "TRIVIAL":
            trivial.append((cat, diff))
        elif s["classification"] == "BUDGET-BOUND":
            budget.append((cat, diff))
        elif s["classification"] == "ROUND-CAPPED":
            rounds.append((cat, diff))

    if trivial:
        print(f"  TRIVIAL cells (make harder): {len(trivial)}")
        for cat, diff in sorted(trivial):
            print(f"    {cat} / {diff}")
    if budget:
        print(f"  BUDGET-BOUND cells (raise --total-budget OR make easier): {len(budget)}")
        for cat, diff in sorted(budget):
            print(f"    {cat} / {diff}")
    if rounds:
        print(f"  ROUND-CAPPED cells (raise --max-rounds OR make easier): {len(rounds)}")
        for cat, diff in sorted(rounds):
            print(f"    {cat} / {diff}")
    if not (trivial or budget or rounds):
        print("  None — tiers look well-calibrated.")
```

- [ ] **Step 7: Handle legacy results files**

Old results (e.g., `gradient_results_alpha.json`) only have `truncated`, not `completion`. Add a helper at module-top that back-fills `completion` if missing. Insert after imports in `analyze_gradient_results.py`:

```python
def _backfill_completion(sample_arm: dict) -> None:
    """Infer completion for a pre-v3 results file that only has `truncated`.

    Legacy ambiguity: a `truncated=True, stop_reason=tool_use` row could be
    max_rounds or budget_exhausted — we can't tell without the harness run
    state. We mark these as 'unknown' rather than guess.
    """
    if "completion" in sample_arm:
        return
    stop = sample_arm.get("stop_reason")
    truncated = sample_arm.get("truncated")
    if not truncated:
        sample_arm["completion"] = "end_turn"
    elif stop == "max_tokens":
        sample_arm["completion"] = "max_tokens"
    else:
        sample_arm["completion"] = "unknown"
```

In `main()` after reading `results`, call it on each arm:

```python
    for r in results:
        if "control" in r:
            _backfill_completion(r["control"])
        if "treatment" in r:
            _backfill_completion(r["treatment"])
```

- [ ] **Step 8: Run analyzer tests — should pass**

```bash
cd algebra-accuracy && python3 -m pytest tests/test_analyze.py -v
```

Expected: 6 tests pass.

- [ ] **Step 9: Smoke test on the alpha results file**

```bash
cd /Users/aalpar/ClaudeProjects/LLMAccuracy && \
  python3 algebra-accuracy/analyze_gradient_results.py \
  --results algebra-accuracy/gradient_results_alpha.json
```

Expected: Runs without error. Since alpha is pre-v3, completion gets back-filled — legacy `monoid_fold/hard` (100% treatment truncated but pre-v3 file) will show as `unknown` in the round-cap column. That's honest.

- [ ] **Step 10: Commit**

```bash
git add algebra-accuracy/analyze_gradient_results.py algebra-accuracy/tests/test_analyze.py
git commit -m "feat(analyze): read completion enum; add ROUND-CAPPED classification

Updates the cell classifier to distinguish BUDGET-BOUND from ROUND-CAPPED
failure modes. Adds TreatRd column to the per-cell table and a new
'round-capped cells' regeneration-target section. Back-fills completion
to 'unknown' for pre-v3 legacy results files."
```

---

## Task 4: Parallelize the main evaluation loop

**Context:** The current loop (evaluate.py:881-909) processes problems serially. At n=90 and ~40s per problem (treatment + control), a run takes ~1 hour. We parallelize with `asyncio` and a pool of N workers, each owning one `WileMCPSession`. Worker count is configurable; default 4.

The key correctness constraints:
1. Each problem must see a fresh Scheme state (`mcp_session.reset()` before each treatment).
2. Results must be written in the same order as the input problems regardless of completion order.
3. The MCP subprocess call is blocking stdio; wrap with `asyncio.to_thread`.

**Files:**
- Modify: `algebra-accuracy/evaluate.py` — add `async def` versions of `run_control` and `run_treatment` and a parallel scheduler
- Create: `algebra-accuracy/tests/test_parallel.py`

- [ ] **Step 1: Write failing test for the parallel scheduler**

Create `algebra-accuracy/tests/test_parallel.py`:

```python
"""Tests for the parallel evaluation scheduler."""
import asyncio
from evaluate import run_parallel_benchmark


def _fake_runner(problem):
    """Synchronous fake — scheduler wraps with to_thread."""
    return {
        "id": problem["id"],
        "result": problem["id"] * 2,  # deterministic mock output
    }


def test_parallel_preserves_order():
    """Output order matches input order even when workers finish out of order."""
    problems = [{"id": i} for i in range(10)]
    results = asyncio.run(
        run_parallel_benchmark(problems, runner=_fake_runner, workers=4)
    )
    assert [r["id"] for r in results] == [p["id"] for p in problems]
    assert [r["result"] for r in results] == [p["id"] * 2 for p in problems]


def test_parallel_single_worker_degenerate():
    """workers=1 should still work (falls back to serial)."""
    problems = [{"id": i} for i in range(3)]
    results = asyncio.run(
        run_parallel_benchmark(problems, runner=_fake_runner, workers=1)
    )
    assert len(results) == 3


def test_parallel_empty_problem_list():
    results = asyncio.run(
        run_parallel_benchmark([], runner=_fake_runner, workers=4)
    )
    assert results == []
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
cd algebra-accuracy && python3 -m pytest tests/test_parallel.py -v
```

Expected: `ImportError` — `run_parallel_benchmark` doesn't exist.

- [ ] **Step 3: Implement `run_parallel_benchmark`**

Add to `evaluate.py`, after the existing session-mode functions (around line 721):

```python
# ── Parallel Scheduler ───────────────────────────────────────────
#
# The main independent-problem loop is embarrassingly parallel: each
# problem is evaluated in isolation. We dispatch N worker tasks that
# pull problems from a shared queue. Each worker holds one MCP subprocess
# (for treatment) since Wile sessions are stateful and reset() is needed
# between problems, not within a parallel fan-out.
#
# Results are indexed by problem position so the final list preserves
# input order regardless of worker completion order.


async def run_parallel_benchmark(problems, runner, workers=4):
    """Run `runner(problem)` across problems with `workers` concurrency.

    `runner` is a synchronous function. It is invoked via asyncio.to_thread
    so worker coroutines can await API calls concurrently without blocking
    the event loop on MCP stdio.

    Returns results in original input order.
    """
    if not problems:
        return []
    workers = max(1, min(workers, len(problems)))

    queue: asyncio.Queue = asyncio.Queue()
    for idx, p in enumerate(problems):
        queue.put_nowait((idx, p))

    results = [None] * len(problems)

    async def worker():
        while True:
            try:
                idx, problem = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                result = await asyncio.to_thread(runner, problem)
                results[idx] = result
            finally:
                queue.task_done()

    await asyncio.gather(*(worker() for _ in range(workers)))
    return results
```

- [ ] **Step 4: Run scheduler tests**

```bash
cd algebra-accuracy && python3 -m pytest tests/test_parallel.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Add a per-problem runner that owns its MCP session**

Also in `evaluate.py`, add a higher-level runner that bundles control + treatment for one problem, using the worker's assigned MCP session:

```python
def _run_one_problem(problem, client, model, mcp_session, tools,
                      condition, total_budget, max_rounds, delay):
    """Evaluate one problem in the requested condition(s).

    Used by the parallel scheduler. Each worker holds its own mcp_session
    so reset()-between-problems can happen without cross-worker contention.
    """
    result = {
        "id": problem["id"],
        "category": problem["category"],
        "difficulty": problem["difficulty"],
        "ground_truth": problem["answer"],
        "answer_type": problem.get("answer_type", "integer"),
        "precision": problem.get("precision"),
    }

    if condition in ("control", "both"):
        ctrl = run_control(client, model, problem, max_tokens=total_budget)
        result["control"] = ctrl
        result["control_correct"] = answers_match(
            ctrl["extracted_answer"], problem["answer"],
            problem.get("answer_type", "integer"),
            precision=problem.get("precision"),
        )
        time.sleep(delay)

    if condition in ("treatment", "both"):
        mcp_session.reset()
        treat = run_treatment(
            client, model, problem, mcp_session, tools,
            total_budget=total_budget,
            max_rounds=max_rounds,
        )
        result["treatment"] = treat
        result["treatment_correct"] = answers_match(
            treat["extracted_answer"], problem["answer"],
            problem.get("answer_type", "integer"),
            precision=problem.get("precision"),
        )
        time.sleep(delay)

    return result
```

- [ ] **Step 6: Add `--workers` CLI flag**

In `main()`, add after `--max-rounds`:

```python
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help=(
            "Number of parallel worker coroutines for the independent "
            "(non-session) evaluation mode. Each worker owns one Wile "
            "MCP subprocess. Default 4. Set to 1 to reproduce serial "
            "behavior."
        ),
    )
```

- [ ] **Step 7: Replace the serial main loop with parallel dispatch**

Replace `evaluate.py:880-909` (the `else:` branch for non-session mode) with:

```python
    else:
        # Parallel independent-problem mode. Each worker owns an MCP
        # session; the scheduler balances problems across workers.
        worker_count = max(1, min(args.workers, len(problems)))
        worker_sessions = [
            WileMCPSession(wile_binary) for _ in range(worker_count)
        ] if args.condition in ("treatment", "both") else [None] * worker_count

        # Each worker needs its own `tools` list — safe to share since
        # Anthropic tool definitions are read-only.
        worker_tools = tools

        worker_slots = asyncio.Queue()
        for session in worker_sessions:
            worker_slots.put_nowait(session)

        def runner(problem):
            # Acquire a session from the pool (blocking here is fine —
            # to_thread already moved us off the event loop).
            # Use asyncio.run_coroutine_threadsafe? No, simpler: use
            # a sync Queue since we're in to_thread land.
            raise RuntimeError("runner must be parameterized with a session")

        # We can't share a single `runner` closure across workers because
        # each worker needs *its own* session. Instead, have each worker
        # coroutine hold its session and call a session-parameterized runner.

        async def worker_task(session):
            nonlocal results
            while True:
                try:
                    idx, problem = await asyncio.to_thread(queue_get_nowait)
                except StopIteration:
                    return
                try:
                    r = await asyncio.to_thread(
                        _run_one_problem, problem, client, args.model,
                        session, worker_tools, args.condition,
                        args.total_budget, args.max_rounds, args.delay,
                    )
                    results[idx] = r
                    print(f"\r  [{sum(1 for x in results if x is not None)}/{len(problems)}]",
                          end="", flush=True, file=sys.stderr)
                except Exception as e:
                    print(f"\nWorker error on {problem['id']}: {e}",
                          file=sys.stderr)
                    results[idx] = {"id": problem["id"], "error": str(e)}

        # Simple shared queue (sync since we're in to_thread when popping)
        import queue as _queue
        _q: _queue.SimpleQueue = _queue.SimpleQueue()
        for idx, p in enumerate(problems):
            _q.put((idx, p))

        def queue_get_nowait():
            try:
                return _q.get_nowait()
            except _queue.Empty:
                raise StopIteration

        results = [None] * len(problems)

        async def main_async():
            await asyncio.gather(*(worker_task(s) for s in worker_sessions))

        asyncio.run(main_async())
        print("", file=sys.stderr)

        # Close worker sessions (except the primary that main's
        # existing close-path handles)
        for session in worker_sessions:
            if session:
                session.close()
        mcp_session = None  # Already closed
```

Note: this is written for correctness over elegance. The complexity comes from pooling MCP subprocesses across async workers. Review this block carefully when implementing.

- [ ] **Step 8: Fix the existing mcp_session close at line 911**

Change:

```python
    if mcp_session:
        mcp_session.close()
```

to just guard against the now-None value — the worker close loop in Step 7 already handles cleanup. Remove this block entirely since `mcp_session` is set to None above.

- [ ] **Step 9: Run a quick 4-problem parallel test**

```bash
cd /Users/aalpar/ClaudeProjects/LLMAccuracy && \
  ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY python3 algebra-accuracy/evaluate.py \
  --problems algebra-accuracy/gradient_problems_v2.json \
  --output /tmp/parallel_smoke.json \
  --model claude-opus-4-7 \
  --condition both \
  --workers 2 \
  --max-rounds 5 \
  --total-budget 2000 \
  --limit 4
```

Expected: Completes in ~1/2 the wall time of the equivalent serial run. Check `/tmp/parallel_smoke.json` has 4 results with `completion` fields populated.

- [ ] **Step 10: Commit**

```bash
git add algebra-accuracy/evaluate.py algebra-accuracy/tests/test_parallel.py
git commit -m "feat(harness): parallelize independent-problem loop via asyncio

Adds --workers flag (default 4) that spawns N async worker coroutines.
Each worker owns one WileMCPSession subprocess since Wile Scheme state
is stateful and reset() is called between problems. Results are kept in
input order regardless of worker completion order. Reduces wall time on
90-problem runs from ~60 min to ~15 min at workers=4."
```

---

## Task 5: Generate n=30 problems for the 3 CALIBRATED cells

**Context:** The 3 cells carrying the substantive claim are `powerset_lattice/medium`, `powerset_lattice/hard`, and `tropical_semiring/hard`. Need 30 problems each (90 total), fresh seed (2026), separate file.

**Files:**
- Create: `algebra-accuracy/gradient_problems_n30.json` (output)

- [ ] **Step 1: Generate 30 problems for the 3 cells**

Three invocations, one per cell (the generator indexes IDs starting at 0 per cell — separate seeds/outputs keep them independent). Each is appended into one JSON file via a small merge:

```bash
cd /Users/aalpar/ClaudeProjects/LLMAccuracy && \
  python3 algebra-accuracy/generate.py \
  --seed 2026 \
  --categories powerset_lattice \
  --difficulty medium \
  --count 30 \
  --output /tmp/pset_med_30.json
```

- [ ] **Step 2: Generate powerset_lattice/hard**

```bash
cd /Users/aalpar/ClaudeProjects/LLMAccuracy && \
  python3 algebra-accuracy/generate.py \
  --seed 2026 \
  --categories powerset_lattice \
  --difficulty hard \
  --count 30 \
  --output /tmp/pset_hard_30.json
```

- [ ] **Step 3: Generate tropical_semiring/hard**

```bash
cd /Users/aalpar/ClaudeProjects/LLMAccuracy && \
  python3 algebra-accuracy/generate.py \
  --seed 2026 \
  --categories tropical_semiring \
  --difficulty hard \
  --count 30 \
  --output /tmp/trop_hard_30.json
```

- [ ] **Step 4: Merge into one file**

```bash
cd /Users/aalpar/ClaudeProjects/LLMAccuracy && \
  python3 -c "
import json
files = ['/tmp/pset_med_30.json', '/tmp/pset_hard_30.json', '/tmp/trop_hard_30.json']
out = []
for f in files:
    out.extend(json.load(open(f)))
json.dump(out, open('algebra-accuracy/gradient_problems_n30.json', 'w'), indent=2)
print(f'Wrote {len(out)} problems')
"
```

Expected: `Wrote 90 problems`.

- [ ] **Step 5: Sanity-check the output**

```bash
python3 -c "
import json
from collections import Counter
p = json.load(open('algebra-accuracy/gradient_problems_n30.json'))
c = Counter((x['category'], x['difficulty']) for x in p)
for k, v in sorted(c.items()): print(k, v)
print('Sample IDs:', [x['id'] for x in p[:5]])
"
```

Expected: 30 problems per cell; 3 cells total.

- [ ] **Step 6: Commit the problem set**

```bash
git add algebra-accuracy/gradient_problems_n30.json
git commit -m "data: n=30 problem set for calibrated cells (seed 2026)

Three cells × 30 problems = 90 total for the n=30 re-run:
- powerset_lattice/medium
- powerset_lattice/hard
- tropical_semiring/hard

These are the CALIBRATED cells from gradient_results_alpha.json — the
only cells whose deltas carry substantive claims about tool interference.
Generated with a fresh seed (2026) distinct from the alpha run's seed 42
to keep the experiments independent."
```

---

## Task 6: Execute the n=30 benchmark run

**Context:** Run both arms on the 90 new problems, with max_rounds=30 (round-cap confound removed) and total_budget=10000 (alpha's budget — no need to change since round-cap was the real issue for these cells). At workers=4, should complete in ~20–30 min.

**Files:**
- Create: `algebra-accuracy/gradient_results_beta.json` (output)

- [ ] **Step 1: Run the benchmark**

```bash
cd /Users/aalpar/ClaudeProjects/LLMAccuracy && \
  ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY python3 algebra-accuracy/evaluate.py \
  --problems algebra-accuracy/gradient_problems_n30.json \
  --output algebra-accuracy/gradient_results_beta.json \
  --model claude-opus-4-7 \
  --condition both \
  --workers 4 \
  --max-rounds 30 \
  --total-budget 10000
```

Expected: Completes in 20–30 min. `gradient_results_beta.json` contains 90 entries with `completion` fields populated.

- [ ] **Step 2: Verify no harness crashes**

```bash
python3 -c "
import json
results = json.load(open('algebra-accuracy/gradient_results_beta.json'))
n_err = sum(1 for r in results if 'error' in r)
print(f'{len(results)} total, {n_err} errors')
"
```

Expected: 90 total, 0 errors.

- [ ] **Step 3: Commit the results file**

```bash
git add algebra-accuracy/gradient_results_beta.json
git commit -m "run: beta results at n=30 with max_rounds=30 on 3 calibrated cells"
```

---

## Task 7: Analyze beta results and report

**Context:** Produce the final analysis comparing alpha (n=10, max_rounds=10) vs beta (n=30, max_rounds=30) for the 3 CALIBRATED cells. Key question: after removing the round-cap confound and increasing n, do treatment deltas on these cells represent real signal or noise?

**Files:**
- Create: `docs/plans/2026-04-19-calibrated-cells-n30-report.md`

- [ ] **Step 1: Run the analyzer on beta**

```bash
cd /Users/aalpar/ClaudeProjects/LLMAccuracy && \
  python3 algebra-accuracy/analyze_gradient_results.py \
  --results algebra-accuracy/gradient_results_beta.json \
  | tee /tmp/beta_analysis.txt
```

Expected: Classification table + regeneration targets.

- [ ] **Step 2: Compute side-by-side comparison with alpha**

```bash
cd /Users/aalpar/ClaudeProjects/LLMAccuracy && \
  python3 -c "
import json
alpha = {(r['category'], r['difficulty']): [] for r in json.load(open('algebra-accuracy/gradient_results_alpha.json'))}
for r in json.load(open('algebra-accuracy/gradient_results_alpha.json')):
    alpha[(r['category'], r['difficulty'])].append(r)
beta = {(r['category'], r['difficulty']): [] for r in json.load(open('algebra-accuracy/gradient_results_beta.json'))}
for r in json.load(open('algebra-accuracy/gradient_results_beta.json')):
    beta[(r['category'], r['difficulty'])].append(r)

cells = [
    ('powerset_lattice', 'medium'),
    ('powerset_lattice', 'hard'),
    ('tropical_semiring', 'hard'),
]
print(f'{\"Cell\":<30} {\"Alpha Δ\":>10} {\"Beta Δ\":>10} {\"Verdict\":<20}')
for cell in cells:
    a = alpha.get(cell, [])
    b = beta.get(cell, [])
    if not a or not b: continue
    a_ctrl = sum(r.get('control_correct', False) for r in a) / len(a)
    a_treat = sum(r.get('treatment_correct', False) for r in a) / len(a)
    b_ctrl = sum(r.get('control_correct', False) for r in b) / len(b)
    b_treat = sum(r.get('treatment_correct', False) for r in b) / len(b)
    a_delta = a_treat - a_ctrl
    b_delta = b_treat - b_ctrl
    print(f'{cell[0]+\"/\"+cell[1]:<30} {a_delta:>+9.0%} {b_delta:>+9.0%}')
" | tee /tmp/alpha_vs_beta.txt
```

- [ ] **Step 3: Write the report**

Create `docs/plans/2026-04-19-calibrated-cells-n30-report.md`. Structure:

```markdown
# Calibrated-Cells n=30 Re-Run — Report

## Setup

- 3 CALIBRATED cells from alpha: powerset_lattice/medium, powerset_lattice/hard, tropical_semiring/hard
- n=30 per cell, fresh seed 2026, max_rounds=30, total_budget=10000
- Model: claude-opus-4-7
- Harness: post-Task-4 parallel version

## Results

[Paste output of Step 1 analyzer]

## Alpha vs Beta Comparison

[Paste output of Step 2 side-by-side]

## Interpretation

[Answer these questions:]

1. **Did removing round-cap change powerset_lattice deltas?** Compare alpha's -10%/-20% to beta. If treatment now matches or beats control, the alpha signal was a round-cap artifact. If deltas persist, tools genuinely interfere with lattice reasoning.

2. **Did tropical_semiring/hard's +40% alpha signal replicate?** With 3x the samples and the same budget headroom, does the delta stay positive? Or was it a small-sample anomaly?

3. **What's the treatment round-cap rate in beta?** If >0 on any cell at max_rounds=30, the confound isn't fully eliminated and we need max_rounds=50 (or a different mechanism).

## Conclusion

[Plain-English summary of what was learned and what to do next.]
```

- [ ] **Step 4: Commit report**

```bash
git add docs/plans/2026-04-19-calibrated-cells-n30-report.md
git commit -m "docs: n=30 re-run report with alpha-vs-beta comparison"
```

- [ ] **Step 5: Push branch and open PR**

```bash
git push -u origin calibrated-cells-n30
gh pr create --title "Harness correctness + n=30 re-run of calibrated cells" \
  --body "$(cat <<'EOF'
## Summary
- Replaces imprecise `truncated` boolean with `completion` enum (end_turn, max_tokens, max_rounds, budget_exhausted)
- Exposes `max_rounds` as CLI flag (default 30, up from hard-coded 10)
- Parallelizes independent-problem loop (4x wall-time reduction)
- Updates analyzer to classify ROUND-CAPPED cells separately
- Re-runs the 3 CALIBRATED cells at n=30 with confound removed

## Context
`gradient_results_alpha.json` reported -20% on `powerset_lattice/hard` — but 9/10 treatment failures hit `max_rounds=10` with `stop_reason=tool_use` and tokens under budget. That's a round-cap confound, not a reasoning failure. This PR fixes the harness and re-measures.

## Test plan
- [x] pytest passes on `tests/test_completion.py`, `tests/test_run_treatment.py`, `tests/test_analyze.py`, `tests/test_parallel.py`
- [x] Smoke test: 4 problems at workers=2, completion field populated
- [x] Full beta run completes in ~25 min at workers=4
- [x] Report compares alpha vs beta deltas; see `docs/plans/2026-04-19-calibrated-cells-n30-report.md`
EOF
)"
```

---

## Self-Review

**Spec coverage:** The user's direction was Option 3 — "Scope smartly when raising n." Target: the 3 CALIBRATED cells at n=30. Checked:
- Scope limited to 3 cells (Task 5): ✓
- n=30 per cell (Task 5): ✓
- "Correct, invasive okay" → replace `truncated`, refactor to async (Tasks 1–4): ✓
- Round-cap confound fixed (Task 2): ✓
- Analyzer reads new field (Task 3): ✓

**Placeholder scan:** None.

**Type consistency:** `classify_completion` signature matches call sites in `run_control`/`run_treatment`/session variants. `summarize_cell` return dict gains `treat_rounds_hit_rate`, `ctrl_completion_counts`, `treat_completion_counts` — all used in the table print and test assertions.

**Potential gap:** Task 4 Step 7 contains a complex async/queue refactor. The code shown is written for correctness but should be reviewed carefully during implementation — the closure-over-session pattern with `asyncio.to_thread` is subtle. If the implementer hits issues, an alternative is to not pool MCP sessions and instead have the serial fallback kick in at `--workers 1`.

**Known trade-off:** `gradient_results_alpha.json` is pre-v3 schema (no `completion`). Task 3 back-fills to `"unknown"` rather than re-running alpha. This means `monoid_fold/hard` from alpha will show as `unknown` in the ROUND-CAPPED column. That's honest — we can't retroactively distinguish its failure mode from the truncated flag alone. If a fully unified view is needed later, re-run alpha with the new harness as a separate task.
