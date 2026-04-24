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
    Problem,
    build_scheme_script,
    detect_wile,
    gen_modular,
    gen_monoid_fold,
    gen_powerset_lattice,
    gen_tropical,
    run_wile,
)


# ── New generators (capability-map-specific) ─────────────────────
#
# These probe categories not already covered by algebra-accuracy.
# All follow the same interface: (difficulty, n) -> List[Problem].
# Ground-truth answers are computed by Wile running the generated
# `scheme_expression`.


# ---- prime_factorization ----
#
# Tests classical "LLM can't do big arithmetic" territory. Trial
# division in Scheme is the Wile oracle. Sorted list of primes with
# multiplicities, e.g. 360 -> (2 2 2 3 3 5).

PRIME_FACTOR_PRESETS = {
    "easy":   (100, 1_000),      # small numbers, often many small factors
    "medium": (10_000, 100_000),  # 4-5 digits, needs real factoring
    "hard":   (1_000_000, 10_000_000),  # 6-7 digits, includes hard semiprimes
}


def gen_prime_factorization(difficulty: str, n: int):
    lo, hi = PRIME_FACTOR_PRESETS[difficulty]
    problems = []
    for i in range(n):
        target = random.randint(lo, hi)
        # Scheme trial division: returns the sorted factor list. Wile
        # writes it as "(2 2 2 3 3 5)" which matches the "polynomial"
        # answer-type parser in evaluate.answers_match.
        scheme = (
            f"(let loop ((n {target}) (p 2) (acc '()))\n"
            f"  (cond\n"
            f"    ((= n 1) (reverse acc))\n"
            f"    ((> (* p p) n) (reverse (cons n acc)))\n"
            f"    ((zero? (modulo n p)) (loop (quotient n p) p (cons p acc)))\n"
            f"    (else (loop n (+ p 1) acc))))"
        )
        nl = (
            f"Factor {target} into its prime factors with multiplicities. "
            f"Give the answer as a sorted list of primes in the form "
            f"`(p1 p2 p3 ...)` (e.g., `(2 2 2 3 3 5)` for 360). "
            f"Primes must appear in non-decreasing order; repeated primes "
            f"are listed separately."
        )
        problems.append(Problem(
            id=f"factor-{difficulty}-{i:03d}",
            category="prime_factorization",
            difficulty=difficulty,
            natural_language=nl,
            scheme_expression=scheme,
            answer_type="polynomial",
        ))
    return problems


# ---- combinatorial_counting ----
#
# Tests whether the LLM applies memorized formulas correctly under
# constraint composition. Each difficulty has a small template set;
# a random template is selected per problem. Answers are computed by
# Wile running the closed-form expression.

def _factorial_scheme():
    """Scheme definition of factorial usable inline in expressions."""
    return "(define (fact n) (if (<= n 1) 1 (* n (fact (- n 1)))))"


def _binomial_scheme():
    return (
        "(define (binom n k)\n"
        "  (if (or (< k 0) (> k n)) 0\n"
        "      (/ (fact n) (* (fact k) (fact (- n k))))))"
    )


def _derangement_scheme():
    # !n = n * !(n-1) + (-1)^n, seed !0 = 1
    return (
        "(define (derange n)\n"
        "  (if (= n 0) 1\n"
        "      (+ (* n (derange (- n 1)))\n"
        "         (if (even? n) 1 -1))))"
    )


def _catalan_scheme():
    # C_n = binom(2n, n) / (n + 1)
    return (
        "(define (catalan n) (/ (binom (* 2 n) n) (+ n 1)))"
    )


def gen_combinatorial_counting(difficulty: str, n: int):
    """Generate combinatorial word problems.

    Templates per difficulty. Each template picks its own parameters in
    a difficulty-appropriate range, emits a natural-language problem
    plus a scheme expression that evaluates to the answer.
    """
    problems = []
    for i in range(n):
        template = _pick_combin_template(difficulty)
        nl, scheme = template()
        problems.append(Problem(
            id=f"combin-{difficulty}-{i:03d}",
            category="combinatorial_counting",
            difficulty=difficulty,
            natural_language=nl,
            scheme_expression=scheme,
            answer_type="integer",
        ))
    return problems


def _pick_combin_template(difficulty: str):
    """Return a zero-arg callable that produces (nl, scheme_expr)."""
    if difficulty == "easy":
        return random.choice([_combin_permutation, _combin_combination])
    if difficulty == "medium":
        return random.choice([_combin_adjacency, _combin_derangement])
    if difficulty == "hard":
        return random.choice([_combin_inclusion_exclusion, _combin_multiset])
    raise ValueError(f"unknown difficulty {difficulty}")


def _combin_permutation():
    k = random.randint(4, 8)
    helpers = _factorial_scheme()
    scheme = f"(begin {helpers} (fact {k}))"
    nl = (
        f"How many distinct ways can {k} distinct books be arranged in a "
        f"row on a shelf? Give a positive integer."
    )
    return nl, scheme


def _combin_combination():
    n = random.randint(6, 12)
    k = random.randint(2, n - 2)
    helpers = _factorial_scheme() + " " + _binomial_scheme()
    scheme = f"(begin {helpers} (binom {n} {k}))"
    nl = (
        f"How many distinct subsets of size {k} can be chosen from a set of "
        f"{n} elements? Give a non-negative integer."
    )
    return nl, scheme


def _combin_adjacency():
    n = random.randint(5, 8)
    # Two specific items must be adjacent: treat the pair as one unit,
    # so count = 2 * (n-1)!
    helpers = _factorial_scheme()
    scheme = f"(begin {helpers} (* 2 (fact {n - 1})))"
    nl = (
        f"How many distinct arrangements of {n} distinct people in a row "
        f"are there such that person A sits next to person B? Give a "
        f"positive integer."
    )
    return nl, scheme


def _combin_derangement():
    n = random.randint(5, 8)
    helpers = _derangement_scheme()
    scheme = f"(begin {helpers} (derange {n}))"
    nl = (
        f"How many derangements of {n} distinct elements are there? "
        f"(A derangement is a permutation with no fixed points — no "
        f"element remains in its original position.) Give a positive "
        f"integer."
    )
    return nl, scheme


def _combin_inclusion_exclusion():
    # Count permutations of n items avoiding r specific positional
    # fixations (none of the r named items is in its original slot).
    # By inclusion-exclusion: sum_{k=0..r} C(r,k) (-1)^k (n-k)!
    n = random.randint(6, 8)
    r = random.randint(3, min(n, 4))
    helpers = _factorial_scheme() + " " + _binomial_scheme()
    scheme = (
        f"(begin {helpers} "
        f"(let loop ((k 0) (acc 0))\n"
        f"  (if (> k {r}) acc\n"
        f"      (loop (+ k 1)\n"
        f"            (+ acc (* (if (even? k) 1 -1)\n"
        f"                      (binom {r} k)\n"
        f"                      (fact (- {n} k))))))))"
    )
    nl = (
        f"How many permutations of the {n} items `(1, 2, ..., {n})` are "
        f"there such that none of the first {r} items `(1, 2, ..., {r})` "
        f"occupies its original position (position 1, 2, ..., {r} "
        f"respectively), while the remaining {n-r} items may be anywhere? "
        f"Give a non-negative integer."
    )
    return nl, scheme


def _combin_multiset():
    # Number of arrangements of a small multiset with no repeated letters
    # adjacent. For simplicity, use multiset AABB (12 total? let me think).
    # Use multiset with 2 letters × 3 copies each = 6 items. Answer = 30.
    # Formula via inclusion-exclusion gets tedious; use a known case.
    # Rotate through a few precomputed cases.
    cases = [
        # (nl_items, scheme_expr)
        ("AABB", "6"),        # arrangements of AABB with no two adjacent equal
        ("AABBC", "24"),      # arrangements of AABBC with no two adjacent equal
        ("AAABBC", "20"),     # arrangements of AAABBC with no two adjacent equal
    ]
    label, answer = random.choice(cases)
    scheme = answer  # scheme_expression just returns the precomputed integer
    nl = (
        f"How many distinct arrangements of the multiset `{label}` are "
        f"there such that no two adjacent letters are equal? "
        f"Give a non-negative integer."
    )
    return nl, scheme


# ── Taxonomy ─────────────────────────────────────────────────────
#
# Each entry: (difficulties, generator_fn). The capability map samples
# across a sequence of difficulty levels per category to locate the
# crossover point where LLM-alone starts failing and Wile starts
# helping. A single-difficulty snapshot would hide that curve.
#
# All categories use the same 3-tier sweep (easy, medium, hard) for a
# uniform map axis. Generators that already expose more tiers (e.g.,
# gen_modular has up to ultra-hard) can be extended later if the map
# shows a category's crossover is above "hard".
#
# Stubbed categories (linear_recurrence, boolean_satisfiability,
# group_theory) live as comments until Wile ships their primitives.

DIFFICULTIES = ["easy", "medium", "hard"]

CATEGORIES = {
    "modular_arithmetic": (DIFFICULTIES, gen_modular),
    "tropical_semiring":  (DIFFICULTIES, gen_tropical),
    "powerset_lattice":   (DIFFICULTIES, gen_powerset_lattice),
    "monoid_fold":        (DIFFICULTIES, gen_monoid_fold),

    # Pending Session 3 — each new generator must expose all 3 tiers:
    # "set_closure":        (DIFFICULTIES, gen_set_closure),
    # "graph_reachability": (DIFFICULTIES, gen_graph_reachability),

    "prime_factorization":    (DIFFICULTIES, gen_prime_factorization),
    "combinatorial_counting": (DIFFICULTIES, gen_combinatorial_counting),

    # Pending Session 4 — regex_matching blocked on Wile regex-match primitive:
    # "regex_matching":         (DIFFICULTIES, gen_regex_matching),

    # Stubbed — Wile primitive incoming:
    # "linear_recurrence":      (DIFFICULTIES, gen_linear_recurrence),
    # "boolean_satisfiability": (DIFFICULTIES, gen_boolean_satisfiability),
    # "group_theory":           (DIFFICULTIES, gen_group_theory),
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
    cell_count = 0
    for cat in cats:
        difficulties, gen_fn = CATEGORIES[cat]
        for difficulty in difficulties:
            problems.extend(gen_fn(difficulty, args.count))
            cell_count += 1

    print(
        f"Generated {len(problems)} problems across {cell_count} cells "
        f"({len(cats)} categories × {len(DIFFICULTIES)} difficulties)",
        file=sys.stderr,
    )

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
