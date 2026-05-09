#!/usr/bin/env python3
"""Capability-Map Analyzer — curve-based per-category classification.

Reads a results JSON produced by evaluate.py and outputs, per category:
  - ctrl_rate and treat_rate at each measured difficulty
  - curve-shape classification: LLM-OWNS-THROUGHOUT, CROSSOVER-FOUND,
    TOOL-ASSISTED-THROUGHOUT, TOOL-INTERFERES, CAPABILITY-GAP, AMBIGUOUS
  - the difficulty bucket where the regime changes (if any)

Classifier thresholds (top of file) are guesses calibrated to give
useful labels at n=5; revisit after seeing real data.

Usage:
    python capability-map/analyze_capability_map.py \\
        --results capability-map/capability_results_sonnet.json
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


DIFFICULTY_ORDER = ["easy", "medium", "hard", "extra-hard", "super-hard"]


# ── Thresholds ────────────────────────────────────────────────────
# These are guesses calibrated for n=5 sampling. With ±20pp resolution,
# the bands need >= 20pp to be discriminable from noise. Loosen if the
# map shows too many AMBIGUOUS; tighten if too many LLM-OWNS.

LLM_OWNS_FLOOR = 0.70          # ctrl floor for LLM-OWNS-THROUGHOUT
TOOL_HELP_DELTA = 0.20         # min delta for "tool helps meaningfully"
CROSSOVER_CTRL_CEIL = 0.50     # ctrl ceiling for crossover detection
GAP_BOTH_FLOOR = 0.30          # both arms below this at hardest = gap


def _rate(samples, arm_key):
    n = len(samples)
    c = sum(1 for r in samples if r.get(arm_key))
    return c / n if n else 0.0


def classify_curve(rates):
    """Classify a category's pair of difficulty curves.

    Args:
        rates: list of (difficulty, ctrl_rate, treat_rate) in DIFFICULTY_ORDER.
    Returns:
        (classification, crossover_difficulty_or_None)
    """
    if not rates:
        return "NO-DATA", None

    # LLM-OWNS-THROUGHOUT: ctrl >= floor at every measured difficulty.
    if all(c >= LLM_OWNS_FLOOR for _, c, _ in rates):
        return "LLM-OWNS-THROUGHOUT", None

    # CROSSOVER-FOUND (checked before CAPABILITY-GAP): a difficulty
    # where ctrl drops below the ceiling AND treat decisively exceeds
    # it. A category with a crossover at medium plus collapse at hard
    # is more usefully labeled by the crossover; the hard-tier gap is
    # supplementary info that the report annotates.
    for d, c, t in rates:
        if c < CROSSOVER_CTRL_CEIL and t >= c + TOOL_HELP_DELTA:
            return "CROSSOVER-FOUND", d

    # CAPABILITY-GAP: at the hardest measured difficulty, both arms <
    # GAP_BOTH_FLOOR — and no crossover was found earlier in the curve.
    # Distinguishes "neither regime ever helps" from "tools help up to
    # a point, then both fail."
    last_d, last_c, last_t = rates[-1]
    if last_c < GAP_BOTH_FLOOR and last_t < GAP_BOTH_FLOOR:
        return "CAPABILITY-GAP", last_d

    # TOOL-INTERFERES: treat <= ctrl - delta at every difficulty.
    if all(t <= c - TOOL_HELP_DELTA for _, c, t in rates):
        return "TOOL-INTERFERES", None

    # TOOL-ASSISTED-THROUGHOUT: treat >= ctrl + delta at every difficulty.
    if all(t >= c + TOOL_HELP_DELTA for _, c, t in rates):
        return "TOOL-ASSISTED-THROUGHOUT", rates[0][0]

    return "AMBIGUOUS", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, required=True)
    args = ap.parse_args()

    data = json.loads(args.results.read_text())
    cells = defaultdict(list)
    for r in data:
        cells[(r["category"], r["difficulty"])].append(r)

    categories = sorted({cat for cat, _ in cells.keys()})

    print(f"{'Category':<28} {'easy':>10} {'medium':>10} {'hard':>10}  "
          f"{'Classification':<26} {'Where'}")
    print("-" * 100)

    summary = defaultdict(list)
    for cat in categories:
        rates_list = []
        for diff in DIFFICULTY_ORDER:
            if (cat, diff) not in cells:
                continue
            samples = cells[(cat, diff)]
            c = _rate(samples, "control_correct")
            t = _rate(samples, "treatment_correct")
            rates_list.append((diff, c, t))

        classification, where = classify_curve(rates_list)
        summary[classification].append((cat, where))

        cells_str = {
            d: f"{int(c * 100):>3d}/{int(t * 100):>3d}"
            for d, c, t in rates_list
        }
        print(
            f"{cat:<28} {cells_str.get('easy', '  -'):>10} "
            f"{cells_str.get('medium', '  -'):>10} "
            f"{cells_str.get('hard', '  -'):>10}  "
            f"{classification:<26} {where or '—'}"
        )

    print()
    print("Territory summary:")
    for label in ("LLM-OWNS-THROUGHOUT", "CROSSOVER-FOUND",
                  "TOOL-ASSISTED-THROUGHOUT", "TOOL-INTERFERES",
                  "CAPABILITY-GAP", "AMBIGUOUS", "NO-DATA"):
        items = summary.get(label, [])
        if not items:
            continue
        names = ", ".join(
            f"{cat}" + (f" ({where})" if where else "")
            for cat, where in items
        )
        print(f"  {label:<28}: {len(items):>2} — {names}")


if __name__ == "__main__":
    main()
