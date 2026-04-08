#!/usr/bin/env python3
"""Independent Python validator for algebra benchmark ground truths.

Reads problems.json, recomputes every answer using pure Python stdlib,
and compares against the Wile-computed ground truth. Shares zero code
with Wile or the algebra library.

Each category has its own evaluator that pattern-matches the known
Scheme AST shape from the generator. Unknown shapes raise ValueError
rather than silently miscomputing.

Usage:
    python algebra-accuracy/validate.py algebra-accuracy/problems.json
    python algebra-accuracy/validate.py --verbose algebra-accuracy/problems.json
"""

import argparse
import json
import sys
from fractions import Fraction


# ── S-expression Parser ──────────────────────────────────────────


def _tokenize(s):
    """Tokenize an S-expression into parens, quote marks, and atoms."""
    tokens = []
    i = 0
    while i < len(s):
        c = s[i]
        if c in " \t\n\r":
            i += 1
        elif c == "(":
            tokens.append("(")
            i += 1
        elif c == ")":
            tokens.append(")")
            i += 1
        elif c == "'":
            tokens.append("'")
            i += 1
        else:
            j = i
            while j < len(s) and s[j] not in " \t\n\r()":
                j += 1
            tokens.append(s[i:j])
            i = j
    return tokens


def _parse_tokens(tokens, pos):
    """Parse tokens starting at pos. Returns (tree, next_pos)."""
    if pos >= len(tokens):
        raise ValueError("unexpected end of tokens")
    tok = tokens[pos]
    if tok == "'":
        inner, nxt = _parse_tokens(tokens, pos + 1)
        return ["quote", inner], nxt
    elif tok == "(":
        pos += 1
        elems = []
        while tokens[pos] != ")":
            elem, pos = _parse_tokens(tokens, pos)
            elems.append(elem)
        return elems, pos + 1
    else:
        return tok, pos + 1


def parse_sexpr(s):
    """Parse an S-expression string into nested lists of strings."""
    tokens = _tokenize(s)
    tree, _ = _parse_tokens(tokens, 0)
    return tree


# ── Modular Arithmetic ──────────────────────────────────────────
#
# Scheme shape: nested (ring-{plus,times,minus} (modular-ring M) A B)
# with integer literals at leaves.


def eval_modular(tree):
    if isinstance(tree, str):
        return int(tree)
    op = tree[0]
    if op not in ("ring-plus", "ring-times", "ring-minus"):
        raise ValueError(f"modular: unexpected op {op!r}")
    mod = int(tree[1][1])  # (modular-ring N) -> N
    a = eval_modular(tree[2])
    b = eval_modular(tree[3])
    if op == "ring-plus":
        return (a + b) % mod
    elif op == "ring-times":
        return (a * b) % mod
    else:
        return (a - b) % mod


# ── Tropical Semiring ───────────────────────────────────────────
#
# Scheme shape: (let ((ts (tropical-semiring))) BODY)
# BODY: nested (semiring-plus ts A B) = min and
#              (semiring-times ts A B) = + with integer leaves.


def eval_tropical(tree):
    if isinstance(tree, str):
        return int(tree)
    op = tree[0]
    if op == "let":
        return eval_tropical(tree[2])
    if op == "semiring-plus":
        return min(eval_tropical(tree[2]), eval_tropical(tree[3]))
    if op == "semiring-times":
        return eval_tropical(tree[2]) + eval_tropical(tree[3])
    raise ValueError(f"tropical: unexpected op {op!r}")


# ── Rational Field ──────────────────────────────────────────────
#
# Scheme shape: nested (field-{plus,times,divide} (rational-field) A B)
# with fraction literals (e.g. "3/4", "-1/3") or integers at leaves.


def eval_rational(tree):
    if isinstance(tree, str):
        return Fraction(tree)
    op = tree[0]
    if op not in ("field-plus", "field-times", "field-divide"):
        raise ValueError(f"rational: unexpected op {op!r}")
    # tree[1] is (rational-field), skip
    a = eval_rational(tree[2])
    b = eval_rational(tree[3])
    if op == "field-plus":
        return a + b
    elif op == "field-times":
        return a * b
    else:
        return a / b


# ── Fixpoint Iteration ─────────────────────────────────────────
#
# Scheme shape:
#   (let ((fl (flat-lattice '(elems...) eqv?)))
#     (fixpoint fl
#       (lambda (v) (cond ((eqv? v (lattice-bottom fl)) V0)
#                         ((eqv? v V0) V1) ...
#                         (else v)))
#       (lattice-bottom fl)))
#
# The cond clauses define a chain: bottom -> V0 -> V1 -> ... -> Vn.
# Vn maps to itself via (else v), so it's the fixpoint.


def eval_fixpoint(tree):
    if tree[0] != "let":
        raise ValueError(f"fixpoint: expected let, got {tree[0]!r}")
    body = tree[2]
    if body[0] != "fixpoint":
        raise ValueError(f"fixpoint: expected fixpoint call, got {body[0]!r}")

    lambda_expr = body[2]
    cond = lambda_expr[2]
    if cond[0] != "cond":
        raise ValueError(f"fixpoint: expected cond, got {cond[0]!r}")

    # Build transfer map from cond clauses
    _BOTTOM = object()
    transfer = {}
    for clause in cond[1:]:
        if clause[0] == "else":
            continue
        test, result = clause[0], int(clause[1])
        source = test[2]  # (eqv? v SOURCE)
        if isinstance(source, list) and source[0] == "lattice-bottom":
            transfer[_BOTTOM] = result
        else:
            transfer[int(source)] = result

    # Iterate from bottom until stable (value not in transfer = else clause)
    v = _BOTTOM
    for _ in range(len(transfer) + 1):
        if v not in transfer:
            break
        v = transfer[v]
    return v


# ── Monoid Power (Modular Exponentiation) ───────────────────────
#
# Scheme shape:
#   (let ((R (modular-ring MOD)))
#     (let loop ((result 1) (count EXP))
#       (if (= count 0) result
#           (loop (ring-times R result BASE) (- count 1)))))


def eval_monoid_power(tree):
    if tree[0] != "let":
        raise ValueError(f"monoid_power: expected let, got {tree[0]!r}")
    mod = int(tree[1][0][1][1])  # [['R', ['modular-ring', MOD]]]

    inner = tree[2]  # named let loop
    if inner[0] != "let" or inner[1] != "loop":
        raise ValueError(f"monoid_power: expected named let loop")
    exp = int(inner[2][1][1])  # [['result','1'], ['count', EXP]]

    # body: (if test result (loop (ring-times R result BASE) ...))
    loop_call = inner[3][3]  # ['loop', ring-times-expr, dec-expr]
    base = int(loop_call[1][3])  # ['ring-times', 'R', 'result', BASE]

    return pow(base, exp, mod)


# ── Powerset Lattice ────────────────────────────────────────────
#
# Scheme shape:
#   (let ((L (powerset-lattice '(elems...)))) BODY)
# BODY: nested (lattice-join L SET SET) = union and
#              (lattice-meet L SET SET) = intersection
# Leaves: '(a b c) = quoted subsets.


def eval_powerset(tree):
    if isinstance(tree, list):
        op = tree[0]
        if op == "let":
            return eval_powerset(tree[2])
        if op == "quote":
            return frozenset(tree[1]) if tree[1] else frozenset()
        if op == "lattice-join":
            return eval_powerset(tree[2]) | eval_powerset(tree[3])
        if op == "lattice-meet":
            return eval_powerset(tree[2]) & eval_powerset(tree[3])
    raise ValueError(f"powerset: unexpected node {tree!r}")


# ── Monoid Fold ─────────────────────────────────────────────────
#
# Scheme shape:
#   (let* ((T (tropical-semiring))
#          (A (semiring->additive-monoid T))
#          (R (modular-ring MOD)))
#     (let loop ((result 1)
#                (vals (list (monoid-fold A '(v ...)) ...)))
#       (if (null? vals) result
#           (loop (ring-times R result (car vals)) (cdr vals)))))
#
# Each monoid-fold computes min of its sequence (tropical additive).
# The loop multiplies the mins together modulo MOD.


def eval_monoid_fold(tree):
    if tree[0] != "let*":
        raise ValueError(f"monoid_fold: expected let*, got {tree[0]!r}")
    mod = int(tree[1][2][1][1])  # bindings[2] = ['R', ['modular-ring', MOD]]

    inner = tree[2]  # named let loop
    if inner[1] != "loop":
        raise ValueError("monoid_fold: expected named let loop")

    # vals binding: ['vals', ['list', fold1, fold2, ...]]
    list_expr = inner[2][1][1]

    result = 1
    for fold in list_expr[1:]:
        if fold[0] != "monoid-fold":
            raise ValueError(f"monoid_fold: expected monoid-fold, got {fold[0]!r}")
        values = [int(v) for v in fold[2][1]]  # ['quote', [v1, v2, ...]]
        result = (result * min(values)) % mod

    return result


# ── Dispatch ────────────────────────────────────────────────────

EVALUATORS = {
    "modular_arithmetic": eval_modular,
    "tropical_semiring": eval_tropical,
    "rational_field": eval_rational,
    "fixpoint": eval_fixpoint,
    "monoid_power": eval_monoid_power,
    "powerset_lattice": eval_powerset,
    "monoid_fold": eval_monoid_fold,
}


# ── Answer Comparison ───────────────────────────────────────────


def parse_wile_answer(answer_str, answer_type):
    """Convert stored Wile answer string to a Python value."""
    if answer_type == "set":
        s = answer_str.strip("()")
        return frozenset(s.split()) if s else frozenset()
    elif answer_type == "fraction":
        return Fraction(answer_str)
    else:
        return int(answer_str)


def format_result(result, answer_type):
    """Format a Python result for display."""
    if answer_type == "set":
        if not result:
            return "()"
        return "(" + " ".join(sorted(result)) + ")"
    return str(result)


# ── Main ────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Validate algebra benchmark answers with pure Python"
    )
    parser.add_argument("problems", help="Path to problems.json")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    with open(args.problems) as f:
        problems = json.load(f)

    passed = 0
    failed = 0
    errors = 0

    for p in problems:
        pid = p["id"]
        cat = p["category"]
        answer_type = p.get("answer_type", "integer")
        wile_answer = p["answer"]

        evaluator = EVALUATORS.get(cat)
        if evaluator is None:
            print(f"SKIP  {pid}: unknown category {cat}")
            continue

        try:
            tree = parse_sexpr(p["scheme_expression"])
            python_result = evaluator(tree)
        except Exception as e:
            print(f"ERROR {pid}: {e}")
            errors += 1
            continue

        wile_val = parse_wile_answer(wile_answer, answer_type)

        if answer_type == "set":
            match = frozenset(python_result) == wile_val
        elif answer_type == "fraction":
            match = Fraction(python_result) == wile_val
        else:
            match = int(python_result) == int(wile_val)

        if match:
            passed += 1
            if args.verbose:
                print(f"  OK  {pid}: {format_result(python_result, answer_type)}")
        else:
            failed += 1
            print(
                f"FAIL  {pid}: "
                f"python={format_result(python_result, answer_type)}  "
                f"wile={wile_answer}"
            )

    total = passed + failed + errors
    print(f"\n{passed}/{total} passed, {failed} failed, {errors} errors")
    sys.exit(1 if failed or errors else 0)


if __name__ == "__main__":
    main()
