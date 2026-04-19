#!/usr/bin/env python3
"""Diagnose per-(category, difficulty) cells from a gradient benchmark run.

Reads a results file produced by evaluate.py (format v2: includes `truncated`
and `total_budget` fields) and prints a table that classifies each cell as:

  TRIVIAL       control ≥ 95%            — tier too easy, not discriminative
  BUDGET-BOUND  control = 0% AND         — cannot measure capability at this budget;
                all failures truncated     either raise budget or reduce difficulty
  CALIBRATED    control 30–70%           — sweet spot, tool advantage shows
  MIXED         anything else            — informative but not pure signal

Also reports treatment stats per cell: success rate, median output tokens,
truncation rate. Any cell where treatment truncates is flagged — 5000-token
budget may be insufficient for that category's harder problems.

Usage:
    python algebra-accuracy/analyze_gradient_results.py \\
        --results algebra-accuracy/gradient_results_v2.json
"""

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path


DIFFICULTY_ORDER = ["easy", "medium", "hard", "extra-hard", "super-hard", "ultra-hard"]


def classify(control_rate: float, all_truncated: bool) -> str:
    """Label a cell by its control-arm behavior."""
    if control_rate >= 0.95:
        return "TRIVIAL"
    if control_rate == 0.0 and all_truncated:
        return "BUDGET-BOUND"
    if 0.30 <= control_rate <= 0.70:
        return "CALIBRATED"
    return "MIXED"


def summarize_cell(samples):
    """Aggregate per-problem samples into cell-level statistics."""
    n = len(samples)
    ctrl_correct = sum(1 for s in samples if s.get("control_correct"))
    treat_correct = sum(1 for s in samples if s.get("treatment_correct"))

    ctrl_truncated = sum(
        1 for s in samples
        if "control" in s and s["control"].get("truncated")
    )
    ctrl_failures_truncated = sum(
        1 for s in samples
        if not s.get("control_correct") and "control" in s and s["control"].get("truncated")
    )
    ctrl_failures = n - ctrl_correct
    all_failures_truncated = (
        ctrl_failures > 0 and ctrl_failures_truncated == ctrl_failures
    )

    treat_truncated = sum(
        1 for s in samples
        if "treatment" in s and s["treatment"].get("truncated")
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
        "ctrl_median_tokens": int(statistics.median(ctrl_tokens)) if ctrl_tokens else 0,
        "treat_median_tokens": int(statistics.median(treat_tokens)) if treat_tokens else 0,
        "classification": classify(ctrl_rate, all_failures_truncated),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", type=Path, required=True, help="Results JSON from evaluate.py")
    args = ap.parse_args()

    results = json.loads(args.results.read_text())
    cells = defaultdict(list)
    for r in results:
        cells[(r["category"], r["difficulty"])].append(r)

    # Detect schema: v2 has `truncated`, older results don't.
    sample = next(iter(results))
    v2 = "control" in sample and "truncated" in sample["control"]
    print(f"Schema: {'v2 (with truncated)' if v2 else 'v1 (legacy)'}")
    if not v2:
        print("WARN: older schema — budget-bound classification unreliable without `truncated` field.")
    print()

    # Table
    print(f"{'Category':<20} {'Difficulty':<12} {'n':>3}  "
          f"{'Ctrl':>6} {'Treat':>6} {'Δ':>6}  "
          f"{'CtrlTrunc':>10} {'CtrlMed':>8} {'TreatMed':>9}  "
          f"{'Classification':<14}")
    print("-" * 105)

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
                f"{s['ctrl_truncated_rate']:>9.0%} {s['ctrl_median_tokens']:>8} {s['treat_median_tokens']:>9}  "
                f"{s['classification']:<14}"
            )
        print()

    # Classification totals
    print(f"── Classification counts (total {sum(summary_counts.values())} cells) ──")
    for label in ("TRIVIAL", "CALIBRATED", "BUDGET-BOUND", "MIXED"):
        print(f"  {label:<14}  {summary_counts.get(label, 0)}")
    print()

    # Regeneration suggestions
    print("── Regeneration targets ──")
    trivial = [(cat, diff) for (cat, diff), samples in cells.items()
               if summarize_cell(samples)["classification"] == "TRIVIAL"]
    budget = [(cat, diff) for (cat, diff), samples in cells.items()
              if summarize_cell(samples)["classification"] == "BUDGET-BOUND"]

    if trivial:
        print(f"  TRIVIAL cells (make harder): {len(trivial)}")
        for cat, diff in sorted(trivial):
            print(f"    {cat} / {diff}")
    if budget:
        print(f"  BUDGET-BOUND cells (raise budget OR make easier): {len(budget)}")
        for cat, diff in sorted(budget):
            print(f"    {cat} / {diff}")
    if not trivial and not budget:
        print("  None — tiers look well-calibrated.")

    # Treatment budget pressure
    treat_truncated_cells = [
        (cat, diff, summarize_cell(samples)["treat_truncated_rate"])
        for (cat, diff), samples in cells.items()
        if summarize_cell(samples)["treat_truncated_rate"] > 0
    ]
    if treat_truncated_cells:
        print()
        print(f"── Treatment truncation (5000-token budget may be tight) ──")
        for cat, diff, rate in sorted(treat_truncated_cells, key=lambda x: -x[2]):
            print(f"  {cat} / {diff}: {rate:.0%} of treatment runs truncated")


if __name__ == "__main__":
    main()
