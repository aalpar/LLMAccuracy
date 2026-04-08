# Ultra-Hard Difficulty Level Design

## Problem

At super-hard difficulty, Sonnet 4.6 achieves 91% accuracy without tools (after fixing the powerset evaluator bug). The tool-assisted treatment only gains +6% — too small to demonstrate value. The benchmark needs harder problems.

## Approach

Shift the entire difficulty scale up: current super-hard becomes new "easy". Old easy through extra-hard are dropped. Five new levels fill out the range above, with ultra-hard as the new ceiling.

New difficulty levels: easy, medium, hard, extra-hard, super-hard, ultra-hard.

## Per-Category Parameters

### Modular Arithmetic

Failure mode: multi-digit multiplication + mod reduction through operation chains.

| Level | Modulus | Operand count | Value range | Nesting |
|---|---|---|---|---|
| easy | ~1000 | 8 | 100-999 | 2 |
| medium | ~5000 | 10 | 500-4999 | 2 |
| hard | ~10000 | 12 | 1000-9999 | 3 |
| extra-hard | ~50000 | 14 | 5000-49999 | 3 |
| super-hard | ~100000 | 16 | 10000-99999 | 4 |
| ultra-hard | ~1000000 | 20 | 100000-999999 | 5 |

### Monoid Power

Failure mode: LLM runs out of output tokens doing step-by-step exponentiation. Already fails at exponents 80-150.

| Level | Base | Exponent | Modulus |
|---|---|---|---|
| easy | 100-999 | 80-150 | ~1000 |
| medium | 500-9999 | 200-500 | ~5000 |
| hard | 1000-9999 | 500-1000 | ~10000 |
| extra-hard | 5000-99999 | 1000-5000 | ~50000 |
| super-hard | 10000-99999 | 5000-10000 | ~100000 |
| ultra-hard | 100000-999999 | 10000-50000 | ~1000000 |

### Tropical Semiring

Failure mode: tracking min vs + through nested operations. LLMs pattern-match on "addition" and apply standard arithmetic.

| Level | Values | Nesting depth |
|---|---|---|
| easy | 16 | 2 |
| medium | 24 | 3 |
| hard | 32 | 3 |
| extra-hard | 40 | 4 |
| super-hard | 48 | 4 |
| ultra-hard | 64 | 5 |

### Rational Field

Failure mode: exact fraction arithmetic with uncommon denominators. Errors compound through operation chains.

| Level | Fraction count | Max denominator |
|---|---|---|
| easy | 7 | 11 |
| medium | 9 | 23 |
| hard | 11 | 47 |
| extra-hard | 13 | 97 |
| super-hard | 15 | 199 |
| ultra-hard | 18 | 499 |

### Fixpoint

Failure mode: tracking state across iteration steps. Current 12-15 steps is trivial (just table lookup). Kept for completeness but expected to remain easy for LLMs at all levels.

| Level | Chain steps | Distractors |
|---|---|---|
| easy | 12-15 | 8 |
| medium | 16-20 | 10 |
| hard | 20-25 | 12 |
| extra-hard | 25-30 | 15 |
| super-hard | 30-40 | 20 |
| ultra-hard | 40-50 | 25 |

### Powerset Lattice

Failure mode: tracking set membership through nested union/intersection. Requires evaluator bug fix (set answer_type normalization).

| Level | Universe size | Operations |
|---|---|---|
| easy | 8 | 6-7 |
| medium | 10 | 8-9 |
| hard | 12 | 10-12 |
| extra-hard | 14 | 13-15 |
| super-hard | 16 | 16-18 |
| ultra-hard | 16 | 20-24 |

### Monoid Fold

Failure mode: composing algebraic operations across sequences. Must identify which monoid does what, then apply correctly.

| Level | Sequences | Seq length | Modulus |
|---|---|---|---|
| easy | 4 | 5 | ~100 |
| medium | 6 | 8 | ~1000 |
| hard | 8 | 10 | ~5000 |
| extra-hard | 10 | 12 | ~10000 |
| super-hard | 12 | 15 | ~50000 |
| ultra-hard | 16 | 20 | ~100000 |

## Implementation

1. Replace all existing difficulty branches in `generate.py` with the new parameter tables
2. Update `DEFAULT_COUNTS` for 6 difficulty levels
3. Update the `--difficulty` choices to include `ultra-hard`
4. Fix the powerset evaluator bug in `evaluate.py` (set answer_type normalization)
5. Update `evaluate.py` difficulty display to handle new levels
