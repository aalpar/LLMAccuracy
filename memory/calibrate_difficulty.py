#!/usr/bin/env python3
"""Difficulty Calibration — probe where Claude's arithmetic capability fails.

Generates a handful of division problems at each of several difficulty
points (operand-digit and precision combinations), runs the control arm
on each (no tools, generous token budget), and reports the success rate
per point. The result is a capability curve we use to pick the easy /
medium / hard presets for the benchmark.

Goal: find the largest (digits, precision) where control ≥ 95% ("easy")
and the smallest where it drops to ≤ 5% ("hard").

Usage:
    python algebra-accuracy/calibrate_difficulty.py \\
        --samples 5 --seed 42 \\
        --model claude-opus-4-7 \\
        --budget 5000 \\
        --output algebra-accuracy/difficulty_calibration.json
"""

import argparse
import json
import os
import random
import statistics
import sys
import time
from dataclasses import asdict
from decimal import ROUND_HALF_EVEN, getcontext
from pathlib import Path
from typing import List

try:
    import anthropic
except ImportError:
    print("Install the Anthropic SDK: pip install anthropic", file=sys.stderr)
    sys.exit(1)

# Tooling lives in memory/ (occasional-use) but reuses the harness in
# algebra-accuracy/. Both paths go on sys.path: memory/ for sibling scripts
# like arithmetic_generate, algebra-accuracy/ for evaluate/generate/grade.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "algebra-accuracy"))
from arithmetic_generate import generate_problem  # noqa: E402
from evaluate import answers_match, run_control  # noqa: E402


# Probe grid: each row is (label, min_digits, max_digits, precision).
#
# Grid history:
#   First run (samples=5, seed=42, budget=5000) measured A–F. Points A
#   through E came in at 100% success. Point F (10–15 digit operands,
#   15 sig digits) measured 20% — but 3 of 4 failures hit `stop_reason=
#   max_tokens`, confounding capability with budget.
#
# This second grid keeps point E as a sanity anchor and extends harder
# to find where capability truly fails. Run with a generous budget
# (e.g. --budget 15000) so `max_tokens` truncation doesn't contaminate
# the signal. That is, we want failures here to be `end_turn` with a
# wrong answer — a true capability miss, not a budget miss.
#
# The user-facing benchmark keeps a tighter budget (5000); the point of
# this calibration is to map the capability curve so anyone wanting to
# extend the benchmark to harder problems knows what budget to plan for.
PROBE_GRID = [
    ("E",  6,  8, 10),   # sanity anchor — known 100%
    ("F", 10, 12, 13),
    ("G", 13, 15, 15),
    ("H", 15, 18, 18),
    ("I", 18, 22, 22),
    ("J", 22, 30, 28),
]


def probe_point(
    client,
    model: str,
    rng: random.Random,
    label: str,
    min_digits: int,
    max_digits: int,
    precision: int,
    samples: int,
    budget: int,
) -> dict:
    """Generate `samples` problems at this difficulty, run control on each."""
    getcontext().prec = precision + 5
    getcontext().rounding = ROUND_HALF_EVEN

    results = []
    for i in range(samples):
        problem = generate_problem(rng, i, min_digits, max_digits, precision)
        problem_dict = asdict(problem)

        t0 = time.perf_counter()
        r = run_control(client, model, problem_dict, max_tokens=budget)
        elapsed = time.perf_counter() - t0

        correct = answers_match(
            r["extracted_answer"],
            problem.answer,
            "decimal",
            precision,
        )
        results.append({
            "id": problem.id,
            "dividend_digits": len(problem.dividend),
            "divisor_digits": len(problem.divisor),
            "output_tokens": r["output_tokens"],
            "stop_reason": r["stop_reason"],
            "extracted_answer": r["extracted_answer"],
            "correct": correct,
            "elapsed_s": round(elapsed, 3),
        })
        status = "✓" if correct else "✗"
        print(
            f"    [{label}-{i}] {status} "
            f"{len(problem.dividend)}d/{len(problem.divisor)}d → {precision} sig, "
            f"out={r['output_tokens']} tok, "
            f"stop={r['stop_reason']}, "
            f"{elapsed:.1f}s",
            flush=True,
        )

    n_correct = sum(1 for r in results if r["correct"])
    toks = [r["output_tokens"] for r in results]
    return {
        "label": label,
        "config": {
            "min_digits": min_digits,
            "max_digits": max_digits,
            "precision": precision,
        },
        "n": samples,
        "n_correct": n_correct,
        "success_rate": round(n_correct / samples, 3),
        "output_tokens": {
            "median": int(statistics.median(toks)),
            "max": max(toks),
        },
        "stop_reasons": _count_stop_reasons(results),
        "samples": results,
    }


def _count_stop_reasons(results: List[dict]) -> dict:
    counts: dict = {}
    for r in results:
        counts[r["stop_reason"]] = counts.get(r["stop_reason"], 0) + 1
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--samples", type=int, default=5, help="Problems per probe point")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed")
    ap.add_argument("--model", default="claude-opus-4-7", help="Anthropic model ID")
    ap.add_argument(
        "--budget",
        type=int,
        default=15000,
        help=(
            "max_tokens for control arm. Default is generous (15000) so "
            "capability is measured without budget truncation. The benchmark "
            "itself runs at a tighter budget (5000, from calibrate_budget.py)."
        ),
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "difficulty_calibration.json",
        help="Output JSON path",
    )
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        ap.error("ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic()
    rng = random.Random(args.seed)

    total_probes = len(PROBE_GRID) * args.samples
    print(f"Probing {len(PROBE_GRID)} difficulty points × {args.samples} samples = {total_probes} control runs")
    print(f"Model: {args.model}  |  Budget: {args.budget} tokens  |  Seed: {args.seed}\n")

    points: List[dict] = []
    for label, min_d, max_d, prec in PROBE_GRID:
        print(f"── Point {label}: {min_d}–{max_d} digit operands, {prec} sig digits ──")
        pt = probe_point(client, args.model, rng, label, min_d, max_d, prec, args.samples, args.budget)
        points.append(pt)
        print(
            f"  → {pt['n_correct']}/{pt['n']} correct "
            f"({pt['success_rate']:.0%}), "
            f"median tokens={pt['output_tokens']['median']}\n"
        )

    output = {
        "model": args.model,
        "budget": args.budget,
        "samples_per_point": args.samples,
        "seed": args.seed,
        "points": points,
    }
    args.output.write_text(json.dumps(output, indent=2) + "\n")

    # Capability curve
    print(f"── Capability curve (wrote {args.output}) ──")
    print(f"  {'pt':<3} {'operands':<10} {'precision':<9} {'success':<10} {'median tokens':<14}")
    for p in points:
        c = p["config"]
        operands = f"{c['min_digits']}–{c['max_digits']}"
        success = f"{p['n_correct']}/{p['n']} ({p['success_rate']:.0%})"
        median = p["output_tokens"]["median"]
        print(f"  {p['label']:<3} {operands:<10} {c['precision']:<9} {success:<10} {median:<14}")

    # Suggest preset mappings
    easy = next((p for p in reversed(points) if p["success_rate"] >= 0.95), None)
    hard = next((p for p in points if p["success_rate"] <= 0.05), None)
    print()
    if easy:
        c = easy["config"]
        print(f"  Easy preset candidate  (≥95%):  point {easy['label']}, operands {c['min_digits']}–{c['max_digits']}, precision {c['precision']}")
    else:
        print("  No probe point achieved ≥95% — grid is too hard; add trivial points (e.g. 1-digit/1-digit, precision 2)")
    if hard:
        c = hard["config"]
        print(f"  Hard preset candidate  (≤5%):   point {hard['label']}, operands {c['min_digits']}–{c['max_digits']}, precision {c['precision']}")
    else:
        print("  No probe point dropped to ≤5% — grid is too easy; extend harder (e.g. 20-digit/15-digit, precision 25)")


if __name__ == "__main__":
    main()
