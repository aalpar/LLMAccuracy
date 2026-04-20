#!/usr/bin/env python3
"""Capability-Map Problem Generator.

Generates a breadth-first sample of problems across the capability-map
taxonomy (see `docs/plans/2026-04-19-capability-map-design.md`). Each
category contributes n problems at a single "medium" difficulty; the
resulting JSON is fed to `algebra-accuracy/evaluate.py` for A/B scoring.

This project intentionally reuses `algebra-accuracy/generate.py`'s
per-category generators rather than copying them — measurements on
shared categories must be directly comparable across the two projects.

Usage:
    python capability-map/generate_capability_problems.py \\
        --wile /usr/local/bin/wile \\
        --output capability-map/capability_problems.json
"""

import argparse
import json
import random
import sys
from dataclasses import asdict
from pathlib import Path


# Reach into algebra-accuracy/ so we can import the shared generators.
# We do not package algebra-accuracy as a Python module; sys.path insertion
# is the same mechanism used inside algebra-accuracy/tests/conftest.py.
_ALGEBRA_ACC = Path(__file__).resolve().parent.parent / "algebra-accuracy"
sys.path.insert(0, str(_ALGEBRA_ACC))

from generate import (  # noqa: E402
    build_scheme_script,
    detect_wile,
    gen_modular,
    gen_monoid_fold,
    gen_powerset_lattice,
    gen_tropical,
    run_wile,
)


# ── Taxonomy ─────────────────────────────────────────────────────
#
# Each entry: (difficulty, generator_fn). The difficulty is a judgment
# call per category — "medium" for the 4 reused generators in Session 2.
# Session 3+ generators land here with their own chosen difficulty.
#
# Stubbed categories (linear_recurrence, boolean_satisfiability,
# group_theory) live as comments until Wile ships their primitives.

CATEGORIES = {
    "modular_arithmetic": ("medium", gen_modular),
    "tropical_semiring":  ("medium", gen_tropical),
    "powerset_lattice":   ("medium", gen_powerset_lattice),
    "monoid_fold":        ("medium", gen_monoid_fold),

    # Pending Session 3:
    # "set_closure":        ("medium", gen_set_closure),
    # "graph_reachability": ("medium", gen_graph_reachability),

    # Pending Session 4:
    # "prime_factorization":    ("medium", gen_prime_factorization),
    # "combinatorial_counting": ("medium", gen_combinatorial_counting),
    # "regex_matching":         ("medium", gen_regex_matching),

    # Stubbed — Wile primitive incoming:
    # "linear_recurrence":      ("medium", gen_linear_recurrence),
    # "boolean_satisfiability": ("medium", gen_boolean_satisfiability),
    # "group_theory":           ("medium", gen_group_theory),
}


N_PER_CELL = 5


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate capability-map problems with Wile ground truth.",
    )
    parser.add_argument(
        "--wile",
        default="/usr/local/bin/wile",
        help="Path to the wile binary (default: /usr/local/bin/wile)",
    )
    parser.add_argument(
        "--seed", type=int, default=2026,
        help="Random seed (default: 2026 — matches the algebra-accuracy "
             "calibrated-cells-n30 run for cross-comparison).",
    )
    parser.add_argument(
        "--count", type=int, default=N_PER_CELL,
        help=f"Per-category problem count (default: {N_PER_CELL}).",
    )
    parser.add_argument(
        "--categories", nargs="+", choices=list(CATEGORIES.keys()),
        help="Subset of categories to generate (default: all active).",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).parent / "capability_problems.json"),
        help="Output file.",
    )
    args = parser.parse_args()

    random.seed(args.seed)
    wile = detect_wile(args.wile)
    print(f"Using Wile: {wile}", file=sys.stderr)

    cats = args.categories or list(CATEGORIES.keys())
    problems = []
    for cat in cats:
        difficulty, gen_fn = CATEGORIES[cat]
        problems.extend(gen_fn(difficulty, args.count))

    print(f"Generated {len(problems)} problems across {len(cats)} categories",
          file=sys.stderr)

    # Compute ground-truth answers via Wile (batched one process invocation).
    script = build_scheme_script(problems)
    answers = run_wile(wile, script)
    if len(answers) != len(problems):
        print(
            f"ERROR: expected {len(problems)} answers, got {len(answers)}",
            file=sys.stderr,
        )
        sys.exit(1)
    for p, ans in zip(problems, answers):
        p.answer = ans

    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump([asdict(p) for p in problems], f, indent=2)
    print(f"Wrote {len(problems)} problems to {output_path}", file=sys.stderr)

    from collections import Counter
    by_cat = Counter((p.category, p.difficulty) for p in problems)
    print("\nSummary:", file=sys.stderr)
    for (cat, diff), count in sorted(by_cat.items()):
        sample = next(
            p for p in problems if p.category == cat and p.difficulty == diff
        )
        print(f"  {cat}/{diff}: {count}  (sample answer: {sample.answer})",
              file=sys.stderr)


if __name__ == "__main__":
    main()
