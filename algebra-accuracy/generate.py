#!/usr/bin/env python3
"""Algebra Accuracy Benchmark — Problem Generator

Generates algebra problems across four categories, computes ground-truth
answers via Wile, and outputs a JSON problem set for A/B evaluation
(LLM alone vs LLM + Wile MCP tools).

All categories exercise (wile algebra) library operations:
  1. Modular arithmetic  — ring-plus/times/minus on modular-ring
  2. Tropical semiring   — semiring-plus/times (⊕ = min, ⊗ = +)
  3. Rational field      — field-plus/times/divide/negate on Q
  4. Fixpoint iteration  — fixpoint on flat-lattice
  5. Monoid power        — monoid-power via ring→semiring→monoid
  6. Powerset lattice    — lattice-join/meet on powerset-lattice
  7. Monoid fold         — monoid-fold with tropical/modular monoids

Usage:
    make build
    python benchmarks/algebra-accuracy/generate.py
    python benchmarks/algebra-accuracy/generate.py --seed 123 --count 20
"""

import argparse
import json
import os
import platform
import random
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from math import gcd
from pathlib import Path
from typing import List, Optional


@dataclass
class Problem:
    id: str
    category: str
    difficulty: str
    natural_language: str
    scheme_expression: str
    answer: str = ""
    answer_type: str = "integer"


REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# ── Wile binary detection ────────────────────────────────────────


def detect_wile(hint: Optional[str] = None) -> Path:
    """Find the Wile binary, checking hint then dist/."""
    if hint:
        p = Path(hint)
        if p.is_file() and os.access(p, os.X_OK):
            return p
        raise FileNotFoundError(f"Not found or not executable: {hint}")

    os_name = platform.system().lower()
    machine = platform.machine()
    arch = "amd64" if machine == "x86_64" else machine

    for candidate in [
        REPO_ROOT / "dist" / os_name / arch / "wile",
        REPO_ROOT / "dist" / "wile",
    ]:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    raise FileNotFoundError(
        "Wile binary not found. Run 'make build' first.\n"
        f"Searched: dist/{os_name}/{arch}/wile, dist/wile"
    )


# ── Modular Arithmetic ──────────────────────────────────────────
#
# Difficulty levers:
#   easy   — small modulus (< 25), 2-digit operands, single operation
#   medium — moderate modulus (31–61), 2-digit operands, 2 chained ops
#   hard   — large modulus (97–131), 3-digit operands, 3–4 chained ops
#
# LLMs degrade on modular arithmetic because they must carry out exact
# integer multiplication (hard for 3+ digits) and then reduce modulo
# a non-power-of-2 prime. Errors compound through chains.


def _mod_deep_chain(R, vals):
    """Build a deep chain: (((a*b+c)*d - e)*f + g)*h ... mod m."""
    # Start with a*b
    expr = f"(ring-times {R} {vals[0]} {vals[1]})"
    nl = f"{vals[0]} \u00d7 {vals[1]}"
    ops = ["plus", "times", "minus", "times", "plus"]
    syms = ["+", "\u00d7", "\u2212", "\u00d7", "+"]
    for j in range(2, len(vals)):
        op = ops[(j - 2) % len(ops)]
        sym = syms[(j - 2) % len(syms)]
        expr = f"(ring-{op} {R} {expr} {vals[j]})"
        nl = f"({nl} {sym} {vals[j]})"
    return expr, nl


def _mod_wide_cross(R, vals):
    """Build a wide cross: (a*b + c*d) * (e*f + g*h) * ... mod m."""
    # Pair up values into products, then alternate plus/times at top level
    pairs = []
    pair_nls = []
    for j in range(0, len(vals) - 1, 2):
        pairs.append(f"(ring-times {R} {vals[j]} {vals[j+1]})")
        pair_nls.append(f"{vals[j]} \u00d7 {vals[j+1]}")
    # Group pairs into sums of two
    groups = []
    group_nls = []
    for j in range(0, len(pairs) - 1, 2):
        groups.append(f"(ring-plus {R} {pairs[j]} {pairs[j+1]})")
        group_nls.append(f"({pair_nls[j]} + {pair_nls[j+1]})")
    if len(pairs) % 2 == 1:
        groups.append(pairs[-1])
        group_nls.append(pair_nls[-1])
    # Multiply groups together
    expr = groups[0]
    nl = group_nls[0]
    for j in range(1, len(groups)):
        expr = f"(ring-times {R} {expr} {groups[j]})"
        nl = f"{nl} \u00d7 {group_nls[j]}"
    return expr, nl


def gen_modular(difficulty: str, n: int) -> List[Problem]:
    params = {
        "easy":       ([997, 1009, 1013, 1019, 1021, 1031], 8, 100, 999),
        "medium":     ([4999, 5003, 5009, 5011, 5021, 5023], 10, 500, 4999),
        "hard":       ([9973, 10007, 10009, 10037, 10039], 12, 1000, 9999),
        "extra-hard": ([49999, 50021, 50023, 50033, 50047], 14, 5000, 49999),
        "super-hard": ([99991, 100003, 100019, 100043, 100049], 16, 10000, 99999),
        "ultra-hard": ([999983, 1000003, 1000033, 1000037, 1000039], 20, 100000, 999999),
    }
    problems = []
    for i in range(n):
        mods, n_vals, lo, hi = params[difficulty]
        mod = random.choice(mods)
        vals = [random.randint(lo, hi) for _ in range(n_vals)]
        R = f"(modular-ring {mod})"

        pat = random.choice(["deep_chain", "wide_cross"])
        if pat == "deep_chain":
            scheme, nl_expr = _mod_deep_chain(R, vals)
        else:
            scheme, nl_expr = _mod_wide_cross(R, vals)

        nl = f"What is {nl_expr} mod {mod}?"

        problems.append(
            Problem(
                id=f"mod-{difficulty}-{i:03d}",
                category="modular_arithmetic",
                difficulty=difficulty,
                natural_language=nl
                + "\nGive only the non-negative numeric answer "
                + "(0 \u2264 answer < modulus).",
                scheme_expression=scheme,
            )
        )
    return problems


# ── Tropical Semiring ────────────────────────────────────────────
#
# The tropical semiring redefines familiar names:
#   ⊕ (addition)       = min       (identity: +∞)
#   ⊗ (multiplication) = ordinary + (identity: 0)
#
# This is the headline benchmark case. LLMs pattern-match on "addition"
# and "multiplication" and apply standard arithmetic. The relabeling
# forces them to override that instinct at every step. Errors grow with
# nesting depth because each operation requires actively suppressing
# the default interpretation.

TROPICAL_PREAMBLE = (
    "In the tropical semiring, the \u2295 operation is min (not addition) "
    "and the \u2297 operation is ordinary addition (not multiplication). "
    "The identity for \u2295 is +\u221e and the identity for \u2297 is 0.\n\n"
)


def _trop_tree(vals, depth):
    """Build a balanced tree of tropical ops over vals at given depth.

    At the leaves (depth 0), values are grouped into pairs with ⊕ (min).
    Each level above alternates ⊗ (add) and ⊕ (min).
    Returns (scheme_expr, nl_expr).
    """
    if len(vals) <= 2:
        if len(vals) == 1:
            return str(vals[0]), str(vals[0])
        return (
            f"(semiring-plus ts {vals[0]} {vals[1]})",
            f"({vals[0]} \u2295 {vals[1]})",
        )

    mid = len(vals) // 2
    left_sch, left_nl = _trop_tree(vals[:mid], depth - 1)
    right_sch, right_nl = _trop_tree(vals[mid:], depth - 1)

    # Alternate: even depth = ⊗ (times/add), odd depth = ⊕ (plus/min)
    if depth % 2 == 0:
        op, sym = "semiring-times", "\u2297"
    else:
        op, sym = "semiring-plus", "\u2295"

    return (
        f"({op} ts {left_sch} {right_sch})",
        f"({left_nl} {sym} {right_nl})",
    )


def gen_tropical(difficulty: str, n: int) -> List[Problem]:
    params = {
        "easy":       (16, 2),
        "medium":     (24, 3),
        "hard":       (32, 3),
        "extra-hard": (40, 4),
        "super-hard": (48, 4),
        "ultra-hard": (64, 5),
    }
    problems = []
    for i in range(n):
        n_vals, depth = params[difficulty]
        vals = [random.randint(1, 100) for _ in range(n_vals)]

        scheme_inner, nl_expr = _trop_tree(vals, depth)
        scheme = f"(let ((ts (tropical-semiring))) {scheme_inner})"

        nl = f"{TROPICAL_PREAMBLE}Compute: {nl_expr}"

        problems.append(
            Problem(
                id=f"trop-{difficulty}-{i:03d}",
                category="tropical_semiring",
                difficulty=difficulty,
                natural_language=nl + "\nGive only the numeric answer.",
                scheme_expression=scheme,
            )
        )
    return problems


# ── Rational Field ───────────────────────────────────────────────
#
# Exact fraction arithmetic. LLMs approximate; Wile computes exactly.
# Difficulty comes from:
#   - Uncommon denominators requiring LCM computation
#   - Chains of operations accumulating complexity
#   - Negative fractions requiring sign tracking


def _rand_frac(max_den=11):
    """Random non-zero fraction with terms up to max_den, in lowest terms."""
    nums = list(range(-max_den, 0)) + list(range(1, max_den + 1))
    dens = list(range(2, max_den + 1))
    num = random.choice(nums)
    den = random.choice(dens)
    g = gcd(abs(num), den)
    return num // g, den // g


def _frac_scheme(n: int, d: int) -> str:
    return str(n) if d == 1 else f"{n}/{d}"


def _frac_nl(n: int, d: int) -> str:
    if d == 1:
        return str(n)
    if n < 0:
        return f"(\u2212{abs(n)}/{d})"
    return f"{n}/{d}"


def _rat_tree(F, fracs, depth):
    """Build a balanced tree of field ops over fracs.

    Returns (scheme_expr, nl_expr).
    """
    if len(fracs) == 1:
        s = _frac_scheme(*fracs[0])
        nl = _frac_nl(*fracs[0])
        return s, nl

    if len(fracs) == 2:
        s0, s1 = _frac_scheme(*fracs[0]), _frac_scheme(*fracs[1])
        nl0, nl1 = _frac_nl(*fracs[0]), _frac_nl(*fracs[1])
        op = random.choice(["plus", "times", "divide"])
        sym = {"plus": "+", "times": "\u00d7", "divide": "\u00f7"}[op]
        return (
            f"(field-{op} {F} {s0} {s1})",
            f"({nl0} {sym} {nl1})",
        )

    mid = len(fracs) // 2
    left_sch, left_nl = _rat_tree(F, fracs[:mid], depth - 1)
    right_sch, right_nl = _rat_tree(F, fracs[mid:], depth - 1)

    op = random.choice(["plus", "times", "divide"])
    sym = {"plus": "+", "times": "\u00d7", "divide": "\u00f7"}[op]
    return (
        f"(field-{op} {F} {left_sch} {right_sch})",
        f"({left_nl} {sym} {right_nl})",
    )


def gen_rational(difficulty: str, n: int) -> List[Problem]:
    params = {
        "easy":       (7, 11),
        "medium":     (9, 23),
        "hard":       (11, 47),
        "extra-hard": (13, 97),
        "super-hard": (15, 199),
        "ultra-hard": (18, 499),
    }
    F = "(rational-field)"
    problems = []

    for i in range(n):
        n_fracs, max_den = params[difficulty]
        fracs = [_rand_frac(max_den) for _ in range(n_fracs)]
        for j in range(n_fracs):
            while fracs[j][0] == 0:
                fracs[j] = _rand_frac(max_den)

        depth = n_fracs  # let the tree determine structure
        scheme, nl_expr = _rat_tree(F, fracs, depth)
        nl = f"Compute exactly: {nl_expr}"

        problems.append(
            Problem(
                id=f"rat-{difficulty}-{i:03d}",
                category="rational_field",
                difficulty=difficulty,
                natural_language=nl
                + "\nGive the answer as a fraction in lowest terms, "
                + "or as an integer if whole.",
                scheme_expression=scheme,
                answer_type="fraction",
            )
        )
    return problems


# ── Fixpoint Iteration ───────────────────────────────────────────
#
# Kleene fixpoint on flat lattices. The transfer function defines a
# chain of steps: ⊥ → v₁ → v₂ → ... → vₙ → vₙ (stable).
#
# Difficulty = chain length. The computation per step is trivial (table
# lookup), but LLMs must track state across N iterations without
# skipping or repeating a step. Distractors (extra lattice elements
# not in the chain) test whether the LLM follows the function definition
# rather than pattern-matching on the element list.


def gen_fixpoint(difficulty: str, n: int) -> List[Problem]:
    params = {
        "easy":       (12, 15, 8),
        "medium":     (16, 20, 10),
        "hard":       (20, 25, 12),
        "extra-hard": (25, 30, 15),
        "super-hard": (30, 40, 20),
        "ultra-hard": (40, 50, 25),
    }
    problems = []
    for i in range(n):
        lo, hi, n_dist = params[difficulty]
        steps = random.randint(lo, hi)

        # Distinct values for the chain
        chain = random.sample(range(1, 100), steps)

        # Distractors: extra lattice elements not in the chain
        available = [x for x in range(1, 100) if x not in chain]
        n_distractors = min(n_dist, len(available))
        distractors = random.sample(available, n_distractors)
        all_elements = sorted(set(chain + distractors))

        # Scheme expression
        elems = " ".join(str(x) for x in all_elements)
        conds = [f"((eqv? v (lattice-bottom fl)) {chain[0]})"]
        for j in range(len(chain) - 1):
            conds.append(f"((eqv? v {chain[j]}) {chain[j + 1]})")
        conds.append("(else v)")
        cond_str = " ".join(conds)

        scheme = (
            f"(let ((fl (flat-lattice '({elems}) eqv?))) "
            f"(fixpoint fl "
            f"(lambda (v) (cond {cond_str})) "
            f"(lattice-bottom fl)))"
        )

        # Natural language
        nl_lines = [
            "A flat lattice has a bottom element \u22a5 and elements "
            f"{{{', '.join(str(x) for x in all_elements)}}}. "
            "All elements are above \u22a5 and below \u22a4, "
            "but incomparable to each other.\n\n"
            "The transfer function f is:",
            f"  f(\u22a5) = {chain[0]}",
        ]
        for j in range(len(chain) - 1):
            nl_lines.append(f"  f({chain[j]}) = {chain[j + 1]}")
        nl_lines.append("  f(x) = x for all other x")
        nl_lines.append(
            "\nStarting from \u22a5, apply f repeatedly until the value "
            "stops changing (Kleene fixpoint iteration). "
            "What is the final value?"
        )

        problems.append(
            Problem(
                id=f"fix-{difficulty}-{i:03d}",
                category="fixpoint",
                difficulty=difficulty,
                natural_language="\n".join(nl_lines)
                + "\nGive only the numeric answer.",
                scheme_expression=scheme,
            )
        )
    return problems


# ── Scheme Script Generation ────────────────────────────────────


def build_scheme_script(problems: List[Problem]) -> str:
    """Build a batch .scm file that evaluates all problems and prints answers."""
    lines = [
        "(import (scheme base)",
        "        (scheme write)",
        "        (wile algebra))",
        "",
    ]
    for p in problems:
        lines.append(f";; {p.id}")
        lines.append(f"(write {p.scheme_expression})")
        lines.append("(newline)")
    return "\n".join(lines)


# ── Execution ────────────────────────────────────────────────────


def run_wile(wile_binary: Path, script: str) -> List[str]:
    """Run a Scheme script via Wile and return output lines."""
    with tempfile.NamedTemporaryFile(
        suffix=".scm", mode="w", delete=False, dir=str(REPO_ROOT)
    ) as f:
        f.write(script)
        tmp = f.name

    try:
        result = subprocess.run(
            [str(wile_binary), "-q", "--file", tmp],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            print(f"Wile error (exit {result.returncode}):", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
            sys.exit(1)
        return [line for line in result.stdout.split("\n") if line]
    finally:
        os.unlink(tmp)


# ── Modular Exponentiation ──────────────────────────────────────
#
# Modular exponentiation via ring-times from the algebra library.
# Each multiplication step uses ring-times on the modular-ring,
# which reduces modulo n after every multiply.
#
# Failure mode: LLMs attempt to compute the full power before
# reducing, or lose track of intermediate values across many
# steps. The library handles reduction exactly at each step.


def gen_monoid_power(difficulty: str, n: int) -> List[Problem]:
    params = {
        "easy":       (100, 999, 80, 150, [997, 1009, 1013, 1019, 1021, 1031]),
        "medium":     (500, 9999, 200, 500, [4999, 5003, 5009, 5011, 5021]),
        "hard":       (1000, 9999, 500, 1000, [9973, 10007, 10009, 10037]),
        "extra-hard": (5000, 99999, 1000, 5000, [49999, 50021, 50023, 50033]),
        "super-hard": (10000, 99999, 5000, 10000, [99991, 100003, 100019, 100043]),
        "ultra-hard": (100000, 999999, 10000, 50000, [999983, 1000003, 1000033, 1000037]),
    }
    problems = []
    for i in range(n):
        base_lo, base_hi, exp_lo, exp_hi, mods = params[difficulty]
        base = random.randint(base_lo, base_hi)
        exp = random.randint(exp_lo, exp_hi)
        mod = random.choice(mods)

        scheme = (
            f"(let ((R (modular-ring {mod})))\n"
            f"  (let loop ((result 1) (count {exp}))\n"
            f"    (if (= count 0) result\n"
            f"        (loop (ring-times R result {base}) "
            f"(- count 1)))))"
        )
        nl = (
            f"Compute {base}^{exp} mod {mod}.\n"
            f"Hint: reduce modulo {mod} after each multiplication "
            f"step rather than computing the full power first.\n"
            f"Give only the non-negative numeric answer "
            f"(0 \u2264 answer < {mod})."
        )

        problems.append(
            Problem(
                id=f"mpow-{difficulty}-{i:03d}",
                category="monoid_power",
                difficulty=difficulty,
                natural_language=nl,
                scheme_expression=scheme,
            )
        )
    return problems


# ── Powerset Lattice ───────────────────────────────────────────
#
# Join = union, meet = intersection on the power set of a universe.
#
# Failure mode: LLMs must track set membership across nested union
# and intersection operations. Errors compound with depth: a single
# missed element in an intermediate union propagates through every
# downstream intersection. The relabeling (join/meet instead of
# union/intersection) adds a translation layer that LLMs can confuse.


def _gen_pset_expr(universe, ops_left):
    """Build a random tree of lattice-join/lattice-meet operations."""
    if ops_left <= 0:
        k = random.randint(1, len(universe) - 1)
        subset = sorted(random.sample(universe, k))
        sch = "'(" + " ".join(subset) + ")"
        nl = "{" + ", ".join(subset) + "}"
        return sch, nl

    op = random.choice(["lattice-join", "lattice-meet"])
    sym = "\u222a" if op == "lattice-join" else "\u2229"

    left_budget = random.randint(0, ops_left - 1)
    right_budget = ops_left - 1 - left_budget

    left_sch, left_nl = _gen_pset_expr(universe, left_budget)
    right_sch, right_nl = _gen_pset_expr(universe, right_budget)

    sch = f"({op} L {left_sch} {right_sch})"
    nl = f"({left_nl} {sym} {right_nl})"
    return sch, nl


def gen_powerset_lattice(difficulty: str, n: int) -> List[Problem]:
    ELEMS = list("abcdefghijklmnop")
    params = {
        "easy":       (8, 6, 7),
        "medium":     (10, 8, 9),
        "hard":       (12, 10, 12),
        "extra-hard": (14, 13, 15),
        "super-hard": (16, 16, 18),
        "ultra-hard": (16, 20, 24),
    }
    problems = []

    for i in range(n):
        n_elems, ops_lo, ops_hi = params[difficulty]
        universe = ELEMS[:n_elems]
        n_ops = random.randint(ops_lo, ops_hi)

        elems_sch = " ".join(universe)
        inner_sch, inner_nl = _gen_pset_expr(universe, n_ops)

        scheme = (
            f"(let ((L (powerset-lattice '({elems_sch})))) "
            f"{inner_sch})"
        )
        nl = (
            f"In the power set lattice on {{{', '.join(universe)}}}, "
            f"where join = union (\u222a) and meet = intersection (\u2229):\n\n"
            f"Compute: {inner_nl}\n\n"
            f"Give the answer as a set in {{a, b, ...}} notation, "
            f"elements in alphabetical order. If empty, write {{}}."
        )

        problems.append(
            Problem(
                id=f"pset-{difficulty}-{i:03d}",
                category="powerset_lattice",
                difficulty=difficulty,
                natural_language=nl,
                scheme_expression=scheme,
                answer_type="set",
            )
        )
    return problems


# ── Monoid Fold ───────────────────────────────────────────────
#
# Fold a sequence using a monoid extracted from an algebraic structure.
# The monoid's operation depends on which structure it came from:
#   tropical additive monoid:       fold = min
#   tropical multiplicative monoid: fold = +
#   modular additive monoid:        fold = sum mod n
#   modular multiplicative monoid:  fold = product mod n
#
# Failure mode: LLMs must identify WHICH operation the monoid performs.
# "Additive monoid of the tropical semiring" sounds like addition but
# is actually min. "Multiplicative monoid" sounds like multiplication
# but is ordinary addition. The algebra-library abstraction layer
# forces the LLM to reason about the structure, not pattern-match
# on keywords.

FOLD_PREAMBLE = (
    "In algebraic structures, a monoid fold applies the monoid's binary "
    "operation across a sequence. Different monoids have different "
    "operations:\n"
    "- Tropical semiring additive monoid: operation is min\n"
    "- Tropical semiring multiplicative monoid: operation is +\n"
    "- Modular ring additive monoid: operation is + (mod n)\n"
    "- Modular ring multiplicative monoid: operation is \u00d7 (mod n)\n\n"
)


def gen_monoid_fold(difficulty: str, n: int) -> List[Problem]:
    # Parameters: (n_seqs, seq_len, mods)
    params = {
        "easy":       (4, 5, [97, 101, 103, 107, 109]),
        "medium":     (6, 8, [997, 1009, 1013, 1019, 1021]),
        "hard":       (8, 10, [4999, 5003, 5009, 5011, 5021]),
        "extra-hard": (10, 12, [9973, 10007, 10009, 10037]),
        "super-hard": (12, 15, [49999, 50021, 50023, 50033]),
        "ultra-hard": (16, 20, [99991, 100003, 100019, 100043]),
    }
    problems = []
    for i in range(n):
        n_seqs, seq_len, mods = params[difficulty]
        mod = random.choice(mods)
        seqs = [
            [random.randint(1, 100) for _ in range(seq_len)]
            for _ in range(n_seqs)
        ]
        vs = [" ".join(str(v) for v in seq) for seq in seqs]

        # Build scheme: modular product of tropical mins
        fold_exprs = "\n                        ".join(
            f"(monoid-fold A '({v}))" for v in vs
        )
        scheme = (
            f"(let* ((T (tropical-semiring))\n"
            f"       (A (semiring->additive-monoid T))\n"
            f"       (R (modular-ring {mod})))\n"
            f"  (let loop ((result 1)\n"
            f"             (vals (list {fold_exprs})))\n"
            f"    (if (null? vals) result\n"
            f"        (loop (ring-times R result (car vals)) "
            f"(cdr vals)))))"
        )

        seq_strs = "\n".join(
            f"  [{', '.join(str(v) for v in seq)}]" for seq in seqs
        )
        mins_str = " \u00d7 ".join(f"min(seq{j+1})" for j in range(n_seqs))
        nl = (
            f"{FOLD_PREAMBLE}"
            f"Compute the product modulo {mod} of the tropical-additive "
            f"folds (min) of these {n_seqs} sequences:\n\n"
            f"{seq_strs}\n\n"
            f"That is: ({mins_str}) mod {mod}.\n\n"
            f"Give only the non-negative numeric answer "
            f"(0 \u2264 answer < {mod})."
        )

        problems.append(
            Problem(
                id=f"mfold-{difficulty}-{i:03d}",
                category="monoid_fold",
                difficulty=difficulty,
                natural_language=nl,
                scheme_expression=scheme,
            )
        )
    return problems



# ── Main ─────────────────────────────────────────────────────────

GENERATORS = {
    "modular_arithmetic": gen_modular,
    "tropical_semiring": gen_tropical,
    "rational_field": gen_rational,
    "fixpoint": gen_fixpoint,
    "monoid_power": gen_monoid_power,
    "powerset_lattice": gen_powerset_lattice,
    "monoid_fold": gen_monoid_fold,
}

# Per-category, per-difficulty problem counts.
# 10 per cell for easy/medium/hard, 5 for extra-hard/super-hard/ultra-hard.
# Fixpoint uses 5 across the board. Override with --count.
DIFFICULTIES = ["easy", "medium", "hard", "extra-hard", "super-hard", "ultra-hard"]
DEFAULT_COUNTS = {
    "modular_arithmetic": {"easy": 10, "medium": 10, "hard": 10, "extra-hard": 5, "super-hard": 5, "ultra-hard": 5},
    "tropical_semiring": {"easy": 10, "medium": 10, "hard": 10, "extra-hard": 5, "super-hard": 5, "ultra-hard": 5},
    "rational_field": {"easy": 10, "medium": 10, "hard": 10, "extra-hard": 5, "super-hard": 5, "ultra-hard": 5},
    "fixpoint": {"easy": 5, "medium": 5, "hard": 5, "extra-hard": 5, "super-hard": 5, "ultra-hard": 5},
    "monoid_power": {"easy": 10, "medium": 10, "hard": 10, "extra-hard": 5, "super-hard": 5, "ultra-hard": 5},
    "powerset_lattice": {"easy": 10, "medium": 10, "hard": 10, "extra-hard": 5, "super-hard": 5, "ultra-hard": 5},
    "monoid_fold": {"easy": 10, "medium": 10, "hard": 10, "extra-hard": 5, "super-hard": 5, "ultra-hard": 5},
}


def main():
    parser = argparse.ArgumentParser(
        description="Generate algebra benchmark problems with Wile ground truth."
    )
    parser.add_argument("--wile", help="Path to wile binary")
    parser.add_argument(
        "--seed", type=int, default=42, help="Random seed (default: 42)"
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).parent / "problems.json"),
        help="Output file (default: problems.json in this directory)",
    )
    parser.add_argument("--count", type=int, help="Override per-cell problem count")
    parser.add_argument(
        "--categories",
        nargs="+",
        choices=list(GENERATORS.keys()),
        help="Categories to generate (default: all)",
    )
    parser.add_argument(
        "--difficulty",
        nargs="+",
        choices=DIFFICULTIES,
        help="Difficulty levels to generate (default: all)",
    )
    args = parser.parse_args()

    random.seed(args.seed)

    wile = detect_wile(args.wile)
    print(f"Using Wile: {wile}", file=sys.stderr)

    # Generate problems
    categories = args.categories or list(GENERATORS.keys())
    difficulties = args.difficulty or DIFFICULTIES
    problems = []
    for cat in categories:
        for diff in difficulties:
            count = args.count or DEFAULT_COUNTS.get(cat, {}).get(diff, 10)
            problems.extend(GENERATORS[cat](diff, count))

    print(f"Generated {len(problems)} problems", file=sys.stderr)

    # Build batch script and compute ground truth via Wile
    script = build_scheme_script(problems)
    answers = run_wile(wile, script)

    if len(answers) != len(problems):
        print(
            f"ERROR: Expected {len(problems)} answers, got {len(answers)}",
            file=sys.stderr,
        )
        for j, line in enumerate(answers):
            print(f"  Line {j}: {line}", file=sys.stderr)
        sys.exit(1)

    for p, ans in zip(problems, answers):
        p.answer = ans

    # Write output
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump([asdict(p) for p in problems], f, indent=2)

    print(f"Wrote {len(problems)} problems to {output_path}", file=sys.stderr)

    # Summary
    from collections import Counter

    by_cell = Counter((p.category, p.difficulty) for p in problems)
    print("\nSummary:", file=sys.stderr)
    for (cat, diff), count in sorted(by_cell.items()):
        sample = next(p for p in problems if p.category == cat and p.difficulty == diff)
        print(f"  {cat}/{diff}: {count} (sample answer: {sample.answer})", file=sys.stderr)


if __name__ == "__main__":
    main()
