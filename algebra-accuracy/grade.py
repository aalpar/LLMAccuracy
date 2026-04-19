#!/usr/bin/env python3
"""Arithmetic Accuracy — Grader for Decimal Division Problems

Grades LLM predictions against ground truth using a digit-wise agreement
metric, the "leading correct digits" (LCD) score:

    LCD(predicted, expected) = length of the longest common prefix of the
    two canonicalised significand digit strings, provided both numbers
    agree in sign and order of magnitude. Zero otherwise.

This metric is robust to where the model "falls off" — it measures how
many significant digits the model got right before it diverged — which is
exactly the signal of interest for a boundary study.

Rounding convention
-------------------
All Decimal comparisons are performed under IEEE-754 §4.3.1 roundTiesToEven
(Python decimal.ROUND_HALF_EVEN). This matches the generator (arithmetic_generate.py)
so a model that rounds correctly in the same mode will agree to the full
requested precision; a model using a different IEEE-754 mode (e.g.
roundTiesToAway, ROUND_HALF_UP) may lose the last digit or two. That
divergence is a *feature* of the metric — it exposes the rounding choice.

Input formats
-------------
Two supported modes:

  1. results.json (as produced by evaluate.py), structure:
     [{id, ground_truth, answer_type,
       control: {extracted_answer, ...}, control_correct: bool,
       treatment: {extracted_answer, ...}, treatment_correct: bool}, ...]

  2. problems.json + responses.json (flat list of {id, predicted}).

Usage
-----
    python algebra-accuracy/grade.py --results results.json
    python algebra-accuracy/grade.py \\
        --problems arithmetic_problems.json \\
        --responses responses.json \\
        --condition control
"""

import argparse
import json
import re
import statistics
import sys
from decimal import (
    ROUND_HALF_EVEN,
    Decimal,
    InvalidOperation,
    getcontext,
    localcontext,
)
from pathlib import Path
from typing import Optional


# Rounding convention used for every Decimal operation here.
# IEEE-754 §4.3.1 roundTiesToEven — matches arithmetic_generate.py.
IEEE754_DEFAULT_ROUNDING = ROUND_HALF_EVEN


# ── Answer parsing ──────────────────────────────────────────────────

_DECIMAL_RE = re.compile(
    r"""
    [-+]?                       # optional sign
    (?:
        \d[\d,_]*\.\d+          # 123,456.789 or 1_234.567
      | \d[\d,_]*\.?            # 1234 or 1234.
      | \.\d+                   # .567
    )
    (?:[eE][-+]?\d+)?           # optional scientific exponent
    """,
    re.VERBOSE,
)


def extract_decimal(text: str) -> Optional[Decimal]:
    """Best-effort extraction of a single Decimal value from model output.

    Handles: commas or underscores as digit separators, scientific notation,
    leading/trailing whitespace, stray text around the number. Takes the
    *last* numeric token in the string — models often restate the question
    and then give the final answer last.
    """
    if text is None:
        return None
    matches = _DECIMAL_RE.findall(text.strip())
    if not matches:
        return None
    cleaned = matches[-1].replace(",", "").replace("_", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


# ── LCD metric ──────────────────────────────────────────────────────


def _canonical(d: Decimal) -> tuple[int, str, int]:
    """Return (sign, significand_digits, adjusted_exponent).

    - sign: 0 for non-negative, 1 for negative (Decimal convention).
    - significand_digits: leading-zero-stripped digit string, no decimal point.
    - adjusted_exponent: power of 10 of the most significant digit.
      (For 0, returns (0, "0", 0).)
    """
    sign, digits, exponent = d.as_tuple()
    if not digits or all(x == 0 for x in digits):
        return (0, "0", 0)
    digit_str = "".join(str(x) for x in digits).lstrip("0") or "0"
    stripped = len(digits) - len(digit_str)
    adj_exp = exponent + len(digits) - 1 - 0  # position of leading nonzero digit
    # adjusted_exponent as defined in Decimal.adjusted(): exponent + digits - 1
    # (stripping leading zeros doesn't change it — they were counted in `digits`
    # but the leading-nonzero is still at the same place value).
    return (sign, digit_str, adj_exp)


def leading_correct_digits(predicted: Decimal, expected: Decimal) -> int:
    """Longest common significand-digit prefix; 0 if sign or magnitude differs.

    Rationale: a model that gets the integer-part digit count wrong (wrong
    magnitude) is not "partially right" — it's off by an order of magnitude
    and should score 0. Only when the model is in the right ballpark do we
    count matching leading digits.
    """
    p_sign, p_dig, p_exp = _canonical(predicted)
    e_sign, e_dig, e_exp = _canonical(expected)

    # Both zero → treat as full match (symbolically).
    if p_dig == "0" and e_dig == "0":
        return max(len(e_dig), 1)

    if p_sign != e_sign or p_exp != e_exp:
        return 0

    n = 0
    for a, b in zip(p_dig, e_dig):
        if a == b:
            n += 1
        else:
            break
    return n


# ── Pass/fail policy ────────────────────────────────────────────────
#
# A prediction passes iff it is an exact match to the ground truth at the
# requested precision, OR off only at the final digit (a rounding-mode
# discrepancy — e.g., the model rounded half-up where the ground truth was
# rounded half-to-even). Larger divergences are genuine computation errors
# and fail.
#
# Operationally: lcd >= precision - 1 captures both cases:
#     lcd == precision     → exact match (full precision agreement).
#     lcd == precision - 1 → disagreement at the last digit only (rounding).
#     lcd <  precision - 1 → computation error at digit (lcd+1) or earlier.


def is_pass(lcd: int, precision: int) -> bool:
    """Return True iff the prediction is an exact match or a last-digit
    rounding mismatch at the requested precision."""
    return lcd >= precision - 1


# ── Grading driver ──────────────────────────────────────────────────


def grade_one(predicted_raw: str, expected_raw: str, precision: int) -> dict:
    """Grade a single (predicted, expected) pair."""
    predicted = extract_decimal(predicted_raw)
    try:
        expected = Decimal(expected_raw)
    except InvalidOperation:
        return {
            "parse_error": f"expected not parseable: {expected_raw!r}",
            "lcd": 0,
            "passed": False,
        }
    if predicted is None:
        return {
            "parse_error": f"predicted not parseable: {predicted_raw!r}",
            "lcd": 0,
            "passed": False,
        }
    lcd = leading_correct_digits(predicted, expected)
    return {
        "predicted": str(predicted),
        "expected": str(expected),
        "lcd": lcd,
        "precision": precision,
        "passed": is_pass(lcd, precision),
    }


def grade_results_file(path: Path, condition: str) -> list[dict]:
    """Grade a results.json file produced by evaluate.py.

    condition: "control" or "treatment" — which field to read predictions from.
    """
    data = json.loads(path.read_text())
    graded = []
    for entry in data:
        block = entry.get(condition, {})
        predicted = block.get("extracted_answer") or block.get("raw_response", "")
        expected = entry["ground_truth"]
        # results.json from evaluate.py doesn't carry the precision; infer from
        # the expected string length (sig-digit count).
        precision = _infer_precision(expected)
        g = grade_one(predicted, expected, precision)
        g["id"] = entry["id"]
        g["difficulty"] = entry.get("difficulty", "")
        graded.append(g)
    return graded


def grade_paired(
    problems_path: Path, responses_path: Path, condition: Optional[str]
) -> list[dict]:
    """Grade a problems.json + responses.json pair.

    responses.json can be:
      - list of {id, predicted}, or
      - dict {id: predicted}, or
      - list of {id, control: {extracted_answer}, treatment: {extracted_answer}}
        (in which case --condition selects the field).
    """
    problems = {p["id"]: p for p in json.loads(problems_path.read_text())}
    raw = json.loads(responses_path.read_text())

    if isinstance(raw, dict):
        responses = raw
    else:
        responses = {}
        for entry in raw:
            rid = entry["id"]
            if condition and condition in entry:
                responses[rid] = entry[condition].get("extracted_answer", "")
            elif "predicted" in entry:
                responses[rid] = entry["predicted"]
            else:
                responses[rid] = ""

    graded = []
    for pid, problem in problems.items():
        expected = problem["answer"]
        precision = problem.get("precision") or _infer_precision(expected)
        predicted = responses.get(pid, "")
        g = grade_one(predicted, expected, precision)
        g["id"] = pid
        g["difficulty"] = problem.get("difficulty", "")
        graded.append(g)
    return graded


def _infer_precision(expected_str: str) -> int:
    """Significant-digit count of a decimal literal (ignores leading zeros & sign)."""
    s = expected_str.lstrip("-+").replace(".", "").lstrip("0")
    return max(len(s), 1)


# ── Reporting ───────────────────────────────────────────────────────


def summarise(graded: list[dict]) -> dict:
    lcds = [g["lcd"] for g in graded if "parse_error" not in g]
    passed = sum(1 for g in graded if g.get("passed"))
    errors = sum(1 for g in graded if "parse_error" in g)
    summary = {
        "n": len(graded),
        "passed": passed,
        "pass_rate": passed / len(graded) if graded else 0.0,
        "parse_errors": errors,
    }
    if lcds:
        summary.update(
            {
                "lcd_mean": statistics.mean(lcds),
                "lcd_median": statistics.median(lcds),
                "lcd_min": min(lcds),
                "lcd_max": max(lcds),
            }
        )
    # By difficulty
    by_diff: dict[str, list[int]] = {}
    for g in graded:
        if "parse_error" in g:
            continue
        by_diff.setdefault(g.get("difficulty", ""), []).append(g["lcd"])
    summary["by_difficulty"] = {
        k: {
            "n": len(v),
            "lcd_mean": statistics.mean(v),
            "lcd_median": statistics.median(v),
        }
        for k, v in by_diff.items()
    }
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--results", type=Path, help="results.json from evaluate.py")
    group.add_argument("--problems", type=Path, help="problems.json (with --responses)")
    ap.add_argument("--responses", type=Path, help="responses.json (with --problems)")
    ap.add_argument(
        "--condition",
        choices=["control", "treatment"],
        default="control",
        help="Which condition's answers to grade (default: control)",
    )
    ap.add_argument("--out", type=Path, help="Write per-problem grades as JSON")
    args = ap.parse_args()

    with localcontext() as ctx:
        ctx.prec = 200
        ctx.rounding = IEEE754_DEFAULT_ROUNDING

        if args.results:
            graded = grade_results_file(args.results, args.condition)
        else:
            if not args.responses:
                ap.error("--responses is required with --problems")
            graded = grade_paired(args.problems, args.responses, args.condition)

    summary = summarise(graded)
    print(json.dumps(summary, indent=2))

    if args.out:
        args.out.write_text(json.dumps(graded, indent=2) + "\n")
        print(f"\nPer-problem grades written to {args.out}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
