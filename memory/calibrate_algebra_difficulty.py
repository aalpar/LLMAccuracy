#!/usr/bin/env python3
"""Algebra Difficulty Calibration — probe the 4 structural categories.

Baseline benchmark (gradient_results_v2.json) showed all 6 tiers of the
four structural categories (fixpoint, monoid_fold, powerset_lattice,
tropical_semiring) land at 100% control success. Claude Opus 4.7 handles
these tasks at every "difficulty" the existing generator defines.

This script probes much-harder parameter points per category to find
where Claude's success rate actually drops. Target three tiers at
success rates ≈100% (easy), ≈50-80% (medium), and ≤20% (hard).

Method: extend each category's PRESETS dict with probe labels
(T1/T2/T3/T4 for tropical, F1/... for fixpoint, etc.), call the
existing generators, compute ground truth via Wile, then run the
control arm at a generous budget to measure success rate.

Usage:
    python algebra-accuracy/calibrate_algebra_difficulty.py \\
        --wile /usr/local/bin/wile \\
        --samples 5 --seed 42 --budget 5000 \\
        --model claude-opus-4-7
"""

import argparse
import json
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Tuple

try:
    import anthropic
except ImportError:
    print("Install the Anthropic SDK: pip install anthropic", file=sys.stderr)
    sys.exit(1)

# Tooling lives in memory/ (occasional-use) but reuses the harness in
# algebra-accuracy/. Both paths go on sys.path so cross-imports resolve.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "algebra-accuracy"))
import generate  # noqa: E402
from evaluate import answers_match, run_control  # noqa: E402


# Probe grids: probe_label → params_tuple. Anchored at each category's
# current "ultra-hard" so the first probe serves as a sanity check;
# subsequent probes push much harder (2x, 4x, 8x depth/size).

TROPICAL_PROBES = {
    "T1": (64, 5),    # = current ultra-hard
    "T2": (128, 6),
    "T3": (256, 7),
    "T4": (512, 8),
}

FIXPOINT_PROBES = {
    "F1": (40, 50, 25),     # = current ultra-hard
    "F2": (60, 80, 40),
    "F3": (80, 120, 60),
    "F4": (100, 150, 80),
}

POWERSET_PROBES = {
    # universe stays at 16 (all letters a..p used), push op count much harder
    "P1": (16, 20, 24),    # = current ultra-hard
    "P2": (16, 30, 40),
    "P3": (16, 50, 70),
    "P4": (16, 80, 120),
}

MONOID_FOLD_PROBES = {
    "M1": (16, 20, [99991, 100003, 100019, 100043]),   # = current ultra-hard
    "M2": (20, 30, [99991, 100003, 100019, 100043]),
    "M3": (30, 50, [99991, 100003, 100019, 100043]),
    "M4": (50, 80, [99991, 100003, 100019, 100043]),
}

CATEGORY_CONFIG: List[Tuple[str, Dict, Dict, str]] = [
    # (category_name, probes_dict, generate_presets_dict, generator_fn_name)
    ("tropical_semiring", TROPICAL_PROBES,    generate.TROPICAL_PRESETS,    "gen_tropical"),
    ("fixpoint",          FIXPOINT_PROBES,    generate.FIXPOINT_PRESETS,    "gen_fixpoint"),
    ("powerset_lattice",  POWERSET_PROBES,    generate.POWERSET_PRESETS,    "gen_powerset_lattice"),
    ("monoid_fold",       MONOID_FOLD_PROBES, generate.MONOID_FOLD_PRESETS, "gen_monoid_fold"),
]


def install_probes_into_presets() -> None:
    """Inject probe labels into generate.py's preset dicts so gen_* can find them."""
    for _, probes, preset_dict, _ in CATEGORY_CONFIG:
        preset_dict.update(probes)


def generate_probe_problems(samples: int) -> List:
    """Create Problem objects for every probe point × samples."""
    problems = []
    for category, probes, _, gen_fn_name in CATEGORY_CONFIG:
        gen_fn = getattr(generate, gen_fn_name)
        for probe_label in probes:
            problems.extend(gen_fn(probe_label, samples))
    return problems


def compute_ground_truth(problems: List, wile_bin: Path) -> None:
    """Run all problems' scheme expressions through Wile; attach answers in place."""
    script = generate.build_scheme_script(problems)
    answers = generate.run_wile(wile_bin, script)
    if len(answers) != len(problems):
        raise RuntimeError(
            f"Expected {len(problems)} answers from Wile, got {len(answers)}"
        )
    for p, ans in zip(problems, answers):
        p.answer = ans


def summarize(results: List[dict]) -> dict:
    n = len(results)
    n_correct = sum(1 for r in results if r["correct"])
    toks = [r["output_tokens"] for r in results]
    stop_counts: Dict[str, int] = {}
    for r in results:
        stop_counts[r["stop_reason"]] = stop_counts.get(r["stop_reason"], 0) + 1
    return {
        "n": n,
        "n_correct": n_correct,
        "success_rate": round(n_correct / n, 3) if n else 0.0,
        "output_tokens": {
            "median": int(statistics.median(toks)) if toks else 0,
            "max": max(toks) if toks else 0,
        },
        "stop_reasons": stop_counts,
        "samples": results,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wile", type=Path, required=True, help="Path to Wile binary")
    ap.add_argument("--samples", type=int, default=5, help="Problems per probe point")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed")
    ap.add_argument("--model", default="claude-opus-4-7", help="Anthropic model ID")
    ap.add_argument(
        "--budget", type=int, default=5000,
        help="Control-arm token budget. 5000 matches the main benchmark; raise to "
             "isolate capability from budget limits.",
    )
    ap.add_argument(
        "--output", type=Path,
        default=Path(__file__).parent / "algebra_difficulty_calibration.json",
        help="Output JSON path",
    )
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        ap.error("ANTHROPIC_API_KEY not set")

    random.seed(args.seed)
    install_probes_into_presets()

    print(f"Generating probe problems ({args.samples} per point × {sum(len(p) for _, p, _, _ in CATEGORY_CONFIG)} points)...", flush=True)
    problems = generate_probe_problems(args.samples)
    print(f"  {len(problems)} problems generated.")

    print(f"Computing ground truth via Wile ({args.wile})...", flush=True)
    compute_ground_truth(problems, args.wile)
    print(f"  All answers computed.\n")

    client = anthropic.Anthropic()
    # Group problems by (category, probe_label) for per-cell reporting
    cell_samples: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    total = len(problems)
    done = 0

    for problem in problems:
        done += 1
        problem_dict = asdict(problem)
        cell_key = (problem.category, problem.difficulty)

        t0 = time.perf_counter()
        r = run_control(client, args.model, problem_dict, max_tokens=args.budget)
        elapsed = time.perf_counter() - t0
        correct = answers_match(
            r["extracted_answer"], problem.answer, problem.answer_type,
        )
        mark = "✓" if correct else "✗"
        print(
            f"  [{done:3d}/{total}] {problem.id} {mark}  "
            f"tokens={r['output_tokens']:5d}  stop={r['stop_reason']:12s}  {elapsed:5.1f}s",
            flush=True,
        )

        cell_samples[cell_key].append({
            "id": problem.id,
            "output_tokens": r["output_tokens"],
            "stop_reason": r["stop_reason"],
            "extracted_answer": r["extracted_answer"],
            "ground_truth": problem.answer,
            "correct": correct,
            "elapsed_s": round(elapsed, 3),
        })

    # Build output: per category, ordered by probe label
    summary: Dict[str, Dict[str, dict]] = {}
    for category, probes, _, _ in CATEGORY_CONFIG:
        summary[category] = {}
        for probe_label in probes:
            key = (category, probe_label)
            if key in cell_samples:
                summary[category][probe_label] = {
                    "params": list(probes[probe_label]) if isinstance(probes[probe_label], tuple) else probes[probe_label],
                    **summarize(cell_samples[key]),
                }

    output = {
        "model": args.model,
        "budget": args.budget,
        "samples_per_point": args.samples,
        "seed": args.seed,
        "categories": summary,
    }
    args.output.write_text(json.dumps(output, indent=2, default=str) + "\n")

    # Human-readable summary per category
    print(f"\n{'='*78}")
    print(f"CAPABILITY CURVE (wrote {args.output})")
    print(f"{'='*78}")
    for category, _, _, _ in CATEGORY_CONFIG:
        print(f"\n── {category} ──")
        print(f"  {'probe':<5} {'params':<30} {'success':<12} {'median tokens':<14}")
        for probe_label, s in summary[category].items():
            params_str = str(s["params"])[:28]
            success = f"{s['n_correct']}/{s['n']} ({s['success_rate']:.0%})"
            median = s["output_tokens"]["median"]
            print(f"  {probe_label:<5} {params_str:<30} {success:<12} {median:<14}")
        # Tier suggestions
        points_sorted = list(summary[category].items())
        easy = next((lbl for lbl, s in reversed(points_sorted) if s["success_rate"] >= 0.95), None)
        medium = next((lbl for lbl, s in points_sorted if 0.30 <= s["success_rate"] <= 0.80), None)
        hard = next((lbl for lbl, s in points_sorted if s["success_rate"] <= 0.20), None)
        print(f"  → easy  candidate: {easy or '(grid too hard — extend easier)'}")
        print(f"  → medium candidate: {medium or '(no probe in 30-80% band)'}")
        print(f"  → hard  candidate: {hard or '(grid too easy — extend harder)'}")


if __name__ == "__main__":
    main()
