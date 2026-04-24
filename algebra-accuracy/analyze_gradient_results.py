#!/usr/bin/env python3
"""Diagnose per-(category, difficulty) cells from a gradient benchmark run.

Reads a results file produced by evaluate.py (format v3: includes `completion`
enum in addition to the legacy `truncated` flag) and prints a table that
classifies each cell as:

  TRIVIAL       control ≥ 95%            — tier too easy, not discriminative
  BUDGET-BOUND  control = 0% AND         — raise --total-budget or reduce
                all failures budget_exhausted difficulty
  ROUND-CAPPED  control = 0% AND         — raise --max-rounds or reduce
                all failures max_rounds   difficulty
  CALIBRATED    control 30–70%           — sweet spot, tool advantage shows
  MIXED         anything else            — informative but not pure signal

Also reports treatment stats per cell: success rate, median output tokens,
max_rounds hit rate. Any cell where treatment frequently hits round caps is
flagged — the --max-rounds default may be insufficient for that category's
harder problems.

Legacy results files (pre-v3, with only `truncated`) are supported via
back-fill: `completion` is inferred where possible and set to `"unknown"`
when ambiguous (truncated with stop_reason == tool_use).

Usage:
    python algebra-accuracy/analyze_gradient_results.py \\
        --results algebra-accuracy/gradient_results_beta.json
"""

import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


DIFFICULTY_ORDER = ["easy", "medium", "hard", "extra-hard", "super-hard", "ultra-hard"]


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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, required=True, help="Results JSON from evaluate.py")
    args = ap.parse_args()

    results = json.loads(args.results.read_text())

    # Back-fill completion for pre-v3 legacy files (had `truncated` only).
    for r in results:
        if "control" in r:
            _backfill_completion(r["control"])
        if "treatment" in r:
            _backfill_completion(r["treatment"])

    cells = defaultdict(list)
    for r in results:
        cells[(r["category"], r["difficulty"])].append(r)

    # Schema detection: if any row carries 'unknown' after back-fill, the
    # source was pre-v3 legacy data with ambiguous truncation.
    has_unknown = any(
        r.get("control", {}).get("completion") == "unknown"
        or r.get("treatment", {}).get("completion") == "unknown"
        for r in results
    )
    if has_unknown:
        print("Schema: legacy (pre-v3) — `completion` back-filled; 'unknown' marks ambiguous rows.")
    else:
        print("Schema: v3 (with completion enum) or clean legacy (no truncations)")
    print()

    # Table
    print(f"{'Category':<20} {'Difficulty':<12} {'n':>3}  "
          f"{'Ctrl':>6} {'Treat':>6} {'Δ':>6}  "
          f"{'CtrlTrunc':>10} {'TreatRd':>8} {'CtrlMed':>8} {'TreatMed':>9}  "
          f"{'Classification':<14}")
    print("-" * 115)

    categories = sorted({cat for cat, _ in cells.keys()})
    summary_counts = defaultdict(int)

    for cat in categories:
        cat_summaries = []
        for diff in DIFFICULTY_ORDER:
            if (cat, diff) not in cells:
                continue
            s = summarize_cell(cells[(cat, diff)])
            cat_summaries.append((diff, s))
            summary_counts[s["classification"]] += 1
            delta = s["treat_rate"] - s["ctrl_rate"]
            print(
                f"{cat:<20} {diff:<12} {s['n']:>3}  "
                f"{s['ctrl_rate']:>5.0%} {s['treat_rate']:>5.0%} {delta:>+5.0%}  "
                f"{s['ctrl_truncated_rate']:>9.0%} {s['treat_rounds_hit_rate']:>7.0%} "
                f"{s['ctrl_median_tokens']:>8} {s['treat_median_tokens']:>9}  "
                f"{s['classification']:<14}"
            )
        print()

    # Classification totals
    print(f"── Classification counts (total {sum(summary_counts.values())} cells) ──")
    for label in ("TRIVIAL", "CALIBRATED", "BUDGET-BOUND", "ROUND-CAPPED", "MIXED"):
        print(f"  {label:<14}  {summary_counts.get(label, 0)}")
    print()

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

    # Treatment budget pressure
    treat_truncated_cells = [
        (cat, diff, summarize_cell(samples)["treat_truncated_rate"])
        for (cat, diff), samples in cells.items()
        if summarize_cell(samples)["treat_truncated_rate"] > 0
    ]
    if treat_truncated_cells:
        print()
        print(f"── Treatment truncation (budget/rounds may be tight) ──")
        for cat, diff, rate in sorted(treat_truncated_cells, key=lambda x: -x[2]):
            print(f"  {cat} / {diff}: {rate:.0%} of treatment runs truncated")


if __name__ == "__main__":
    main()
