#!/usr/bin/env python3
"""Arithmetic Accuracy — Division Problem Generator

Generates division problems at calibrated difficulty tiers (easy / medium /
hard) and computes exact decimal ground-truth using Python's `decimal` module.

Tier parameters come from algebra-accuracy/difficulty_calibration.json,
which measured Claude Opus 4.7's capability at a 15000-token budget and
projected to the benchmark budget (5000 tokens):

  easy   (6–8 digit operands, 10 sig digits): 100% control success
  medium (10–12 digit operands, 13 sig digits): ~100% capability, ~40%
         at benchmark budget — the tier where tool advantage shows
  hard   (22–30 digit operands, 28 sig digits): 0% at benchmark budget
         (Claude can do the math given enough tokens, but not within
         the 5000-token envelope)

No floats are used anywhere. All arithmetic goes through `Decimal`.
Answers are rounded at the configured precision using IEEE-754
roundTiesToEven (banker's rounding).

Enforcement: dividend ≥ divisor. Random sampling can produce
dividend < divisor cases where the quotient is 0.0XX... — these
systematically cost ~70% more tokens (see difficulty_calibration
analysis). Swapping operands post-hoc eliminates that variance
source without narrowing the problem distribution.

Output matches the JSON schema used by evaluate.py.

Usage:
    python algebra-accuracy/arithmetic_generate.py --preset all
    python algebra-accuracy/arithmetic_generate.py --preset easy --count 30
    python algebra-accuracy/arithmetic_generate.py \\
        --min-digits 40 --max-digits 80 --precision 100   # custom mode
"""

import argparse
import json
import random
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_EVEN, getcontext
from pathlib import Path
from typing import List


# ── Rounding convention (IEEE-754 §4.3) ─────────────────────────────
#
# We use roundTiesToEven (IEEE-754's default), which is Python's
# decimal.ROUND_HALF_EVEN. Also known as "banker's rounding":
#   - non-tie values round to nearest
#   - ties (exactly halfway) round to the nearest even last digit
#
# Mapping IEEE-754 → Python decimal module:
#   roundTiesToEven      → ROUND_HALF_EVEN   (used here — IEEE-754 default)
#   roundTiesToAway      → ROUND_HALF_UP
#   roundTowardPositive  → ROUND_CEILING
#   roundTowardNegative  → ROUND_FLOOR
#   roundTowardZero      → ROUND_DOWN
#
# Grading must use the same mode, or divisions landing exactly on ties
# will disagree in the last digit. See grade.py.

IEEE754_DEFAULT_ROUNDING = ROUND_HALF_EVEN  # IEEE-754 §4.3.1 roundTiesToEven


# ── Difficulty Presets ──────────────────────────────────────────────
#
# Calibrated against Claude Opus 4.7 via algebra-accuracy/calibrate_difficulty.py.
# Benchmark budget is 5000 tokens (from calibrate_budget.py). Numbers here
# name the expected control-arm success rate at that budget.
#
# If you change the benchmark budget or the model, these presets should be
# re-derived — don't treat them as universal constants.

DIFFICULTY_PRESETS = {
    "easy":   {"min_digits":  6, "max_digits":  8, "precision": 10},
    "medium": {"min_digits": 10, "max_digits": 12, "precision": 13},
    "hard":   {"min_digits": 22, "max_digits": 30, "precision": 28},
}


@dataclass
class Problem:
    id: str
    category: str
    difficulty: str
    natural_language: str
    dividend: str
    divisor: str
    precision: int
    answer: str
    answer_type: str = "decimal"


def random_integer_with_digits(rng: random.Random, n_digits: int) -> int:
    """Uniform random integer in [10^(n-1), 10^n - 1]."""
    if n_digits < 1:
        raise ValueError(f"n_digits must be >= 1, got {n_digits}")
    lo = 10 ** (n_digits - 1)
    hi = 10**n_digits - 1
    return rng.randint(lo, hi)


def generate_problem(
    rng: random.Random,
    index: int,
    min_digits: int,
    max_digits: int,
    precision: int,
    difficulty: str = "custom",
) -> Problem:
    n_a = rng.randint(min_digits, max_digits)
    n_b = rng.randint(min_digits, max_digits)
    a = random_integer_with_digits(rng, n_a)
    b = random_integer_with_digits(rng, n_b)

    # Enforce dividend >= divisor. Eliminates the small-quotient (0.0XX...)
    # cases that cost ~70% more tokens on average — a hidden variance source
    # observed during difficulty calibration (see module docstring).
    if a < b:
        a, b = b, a

    # Exact decimal division at the configured precision.
    # Context precision is set globally before generate_problem is called.
    quotient = Decimal(a) / Decimal(b)

    # Canonical string form: no exponent notation, no trailing zeros beyond
    # the precision boundary. Decimal's str() is deterministic and round-trippable.
    answer = format(quotient, "f")

    nl = (
        f"Compute the following division to {precision} significant digits.\n"
        f"Dividend: {a}\n"
        f"Divisor:  {b}\n"
        f"Give your answer as a decimal number. Do not use scientific notation. "
        f"Round the {precision}th significant digit using IEEE-754 roundTiesToEven "
        f"(banker's rounding: ties go to the nearest even digit)."
    )

    return Problem(
        id=f"div-{index:04d}",
        category="decimal_division",
        difficulty=difficulty,
        natural_language=nl,
        dividend=str(a),
        divisor=str(b),
        precision=precision,
        answer=answer,
    )


def _generate_tier(
    rng: random.Random,
    tier: str,
    start_index: int,
    count: int,
    min_digits: int,
    max_digits: int,
    precision: int,
) -> List[Problem]:
    """Generate `count` problems for a single tier with shared Decimal context."""
    ctx = getcontext()
    ctx.prec = precision + 5
    ctx.rounding = IEEE754_DEFAULT_ROUNDING
    return [
        generate_problem(rng, start_index + i, min_digits, max_digits, precision, tier)
        for i in range(count)
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--preset",
        choices=sorted(DIFFICULTY_PRESETS.keys()) + ["all"],
        help="Use a calibrated preset: easy, medium, hard, or all (all tiers).",
    )
    ap.add_argument(
        "--count",
        type=int,
        default=20,
        help="Number of problems per tier (or total in custom mode). Default 20.",
    )
    ap.add_argument("--min-digits", type=int, help="Custom mode: min digits per operand")
    ap.add_argument("--max-digits", type=int, help="Custom mode: max digits per operand")
    ap.add_argument("--precision", type=int, help="Custom mode: significant digits of precision")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    ap.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "arithmetic_problems.json",
        help="Output JSON path",
    )
    args = ap.parse_args()

    custom_mode = any(x is not None for x in (args.min_digits, args.max_digits, args.precision))
    if args.preset and custom_mode:
        ap.error("--preset and --min-digits/--max-digits/--precision are mutually exclusive")
    if not args.preset and not custom_mode:
        ap.error("specify either --preset {easy|medium|hard|all} or all of --min-digits/--max-digits/--precision")

    rng = random.Random(args.seed)
    problems: List[Problem] = []

    if args.preset == "all":
        for tier in ("easy", "medium", "hard"):
            cfg = DIFFICULTY_PRESETS[tier]
            problems.extend(_generate_tier(
                rng, tier, len(problems), args.count,
                cfg["min_digits"], cfg["max_digits"], cfg["precision"],
            ))
    elif args.preset:
        cfg = DIFFICULTY_PRESETS[args.preset]
        problems.extend(_generate_tier(
            rng, args.preset, 0, args.count,
            cfg["min_digits"], cfg["max_digits"], cfg["precision"],
        ))
    else:
        if None in (args.min_digits, args.max_digits, args.precision):
            ap.error("custom mode requires all of --min-digits, --max-digits, --precision")
        if args.min_digits < 1 or args.max_digits < args.min_digits:
            ap.error("require 1 <= --min-digits <= --max-digits")
        if args.precision < 1:
            ap.error("--precision must be >= 1")
        problems.extend(_generate_tier(
            rng, "custom", 0, args.count,
            args.min_digits, args.max_digits, args.precision,
        ))

    args.output.write_text(json.dumps([asdict(p) for p in problems], indent=2) + "\n")

    # Summary
    by_difficulty: dict[str, int] = {}
    for p in problems:
        by_difficulty[p.difficulty] = by_difficulty.get(p.difficulty, 0) + 1
    print(f"Wrote {len(problems)} problems to {args.output}")
    for k in ("easy", "medium", "hard", "custom"):
        if k in by_difficulty:
            cfg = DIFFICULTY_PRESETS.get(k)
            extra = f"  ({cfg['min_digits']}–{cfg['max_digits']}d, {cfg['precision']} sig)" if cfg else ""
            print(f"  {k}: {by_difficulty[k]}{extra}")


if __name__ == "__main__":
    main()
