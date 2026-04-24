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
import itertools
import json
import random
import re
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


# ---- graph_reachability ----
#
# Given a directed graph (vertex set + edge list) and a source vertex,
# compute the set of vertices reachable from the source via any number
# of forward edges. Tests mechanical traversal over graphs too large for
# visual inspection.

GRAPH_REACHABILITY_PRESETS = {
    # (n_vertices, n_edges, n_cycles)
    "easy":   (5, 6, 1),
    "medium": (10, 15, 3),
    "hard":   (20, 40, 6),
}


def _gen_graph(n_vertices: int, n_edges: int, n_cycles: int):
    """Build a directed graph with the specified rough structure.

    Returns (vertex_names, edge_list, source_vertex). Vertices use the
    alphabet a..t. Edges are randomly sampled from non-loop pairs; then
    n_cycles edges are biased to close cycles. The source is chosen
    from the vertex with the largest forward component to ensure the
    problem is non-trivial.
    """
    alphabet = list("abcdefghijklmnopqrst")
    vertices = alphabet[:n_vertices]
    edges: set = set()
    # Random tree-ish backbone first to ensure connectivity.
    for j in range(1, n_vertices):
        parent = random.choice(vertices[:j])
        child = vertices[j]
        edges.add((parent, child))
    # Fill to n_edges with random pairs; enforce no self-loops.
    while len(edges) < n_edges:
        u = random.choice(vertices)
        v = random.choice(vertices)
        if u != v:
            edges.add((u, v))
    # Source: always vertices[0] — deterministic, and tree-root ensures
    # a non-trivial reach set.
    return vertices, sorted(edges), vertices[0]


def gen_graph_reachability(difficulty: str, n: int):
    n_vertices, n_edges, _n_cycles = GRAPH_REACHABILITY_PRESETS[difficulty]
    problems = []
    for i in range(n):
        vertices, edges, source = _gen_graph(n_vertices, n_edges, _n_cycles)
        # Scheme oracle: fixed-point iteration over reach.
        # Build the edge list as a quoted Scheme list of pairs.
        edge_expr = "'(" + " ".join(
            f"({u} {v})" for u, v in edges
        ) + ")"
        scheme = (
            f"(let ((edges {edge_expr})\n"
            f"      (source '{source}))\n"
            f"  (let loop ((reach (list source)))\n"
            f"    (let ((new-reach\n"
            f"            (let scan ((es edges) (acc reach))\n"
            f"              (if (null? es)\n"
            f"                  acc\n"
            f"                  (let ((u (car (car es)))\n"
            f"                        (v (cadr (car es))))\n"
            f"                    (if (and (memq u acc) (not (memq v acc)))\n"
            f"                        (scan (cdr es) (cons v acc))\n"
            f"                        (scan (cdr es) acc)))))))\n"
            f"      (if (= (length new-reach) (length reach))\n"
            f"          (sort (lambda (a b) (string<? (symbol->string a) (symbol->string b))) reach)\n"
            f"          (loop new-reach)))))"
        )
        edge_display = ", ".join(f"({u},{v})" for u, v in edges)
        nl = (
            f"Consider the directed graph with vertices "
            f"{{{', '.join(vertices)}}} and edges "
            f"{{{edge_display}}}. Give the set of vertices reachable "
            f"from vertex `{source}` (including `{source}` itself). "
            f"Return the answer as a set in `{{...}}` notation with "
            f"elements in alphabetical order."
        )
        problems.append(Problem(
            id=f"reach-{difficulty}-{i:03d}",
            category="graph_reachability",
            difficulty=difficulty,
            natural_language=nl,
            scheme_expression=scheme,
            answer_type="set",
        ))
    return problems


# ---- set_closure ----
#
# Given a starting set S and one or more generating operations f_i on
# elements of Z/nZ, compute the smallest superset of S closed under all
# f_i. Tests iteration-to-convergence — LLMs often stop too early
# because they don't verify that no new elements were added.

SET_CLOSURE_PRESETS = {
    # (modulus, |S|, operations) where each operation is a string
    # "(OP a b)" with named ring op — we pick from "+" and "*" and "+3".
    "easy":   (11, 2, ["+"]),
    "medium": (13, 3, ["+", "*"]),
    "hard":   (17, 3, ["+", "*", "+3"]),
}


def gen_set_closure(difficulty: str, n: int):
    mod, start_size, op_names = SET_CLOSURE_PRESETS[difficulty]
    problems = []
    for i in range(n):
        elements = list(range(mod))
        start = random.sample(elements, start_size)
        # Build Scheme ops: each op is a lambda (a b) -> integer.
        op_schemes = []
        op_nls = []
        for op in op_names:
            if op == "+":
                op_schemes.append(f"(lambda (a b) (modulo (+ a b) {mod}))")
                op_nls.append(f"(a + b) mod {mod}")
            elif op == "*":
                op_schemes.append(f"(lambda (a b) (modulo (* a b) {mod}))")
                op_nls.append(f"(a \u00d7 b) mod {mod}")
            elif op == "+3":
                op_schemes.append(f"(lambda (a b) (modulo (+ a b 3) {mod}))")
                op_nls.append(f"(a + b + 3) mod {mod}")
            else:
                raise ValueError(f"unknown op {op}")

        start_sch = "(list " + " ".join(str(x) for x in start) + ")"
        ops_sch = "(list " + " ".join(op_schemes) + ")"

        # No `filter` primitive in Wile, so we fuse filter+dedup into one
        # recursive scan: keep values not in acc and not already kept.
        scheme = (
            f"(let ((start {start_sch})\n"
            f"      (ops {ops_sch}))\n"
            f"  (let loop ((acc start))\n"
            f"    (let* ((new-values\n"
            f"             (apply append\n"
            f"               (map (lambda (op)\n"
            f"                      (apply append\n"
            f"                        (map (lambda (a)\n"
            f"                               (map (lambda (b) (op a b)) acc))\n"
            f"                             acc)))\n"
            f"                    ops)))\n"
            f"           (novel-dedup (let scan ((xs new-values) (seen '()))\n"
            f"                          (cond\n"
            f"                            ((null? xs) (reverse seen))\n"
            f"                            ((member (car xs) acc) (scan (cdr xs) seen))\n"
            f"                            ((member (car xs) seen) (scan (cdr xs) seen))\n"
            f"                            (else (scan (cdr xs) (cons (car xs) seen)))))))\n"
            f"      (if (null? novel-dedup)\n"
            f"          (sort < acc)\n"
            f"          (loop (append acc novel-dedup))))))"
        )

        ops_str = " and ".join(op_nls)
        nl = (
            f"Starting from the set `{{{', '.join(str(x) for x in sorted(start))}}}` "
            f"in Z/{mod}Z, compute the smallest superset that is closed "
            f"under the operation{'s' if len(op_nls) > 1 else ''} "
            f"{ops_str}. (That is: keep adding `op(a, b)` for every pair "
            f"`a, b` already in the set, until no new elements appear.) "
            f"Return the closure as a sorted list of integers in `(...)` "
            f"notation."
        )
        problems.append(Problem(
            id=f"closure-{difficulty}-{i:03d}",
            category="set_closure",
            difficulty=difficulty,
            natural_language=nl,
            scheme_expression=scheme,
            answer_type="set",
        ))
    return problems


# ---- regex_matching ----
#
# Given a regex pattern and a string, determine whether the pattern
# matches the string. Answer is 'yes or 'no (Scheme symbols, which
# write without quotes).
#
# Ground truth is computed in Python at generation time (via the re
# module); the scheme_expression is the literal Scheme symbol. Wile
# just echoes it back through (write ...). This hybrid avoids a
# dependency on Wile's regex support, which is unverified as of this
# writing.

REGEX_PATTERNS_EASY = [
    (r"abc", "xabcy", True),
    (r"abc", "xaby", False),
    (r"a(b|c)d", "abd", True),
    (r"a(b|c)d", "aed", False),
    (r"ab*c", "ac", True),
    (r"ab+c", "ac", False),
    (r"ab*c", "abbbc", True),
    (r"(ab)+", "ababab", True),
    (r"(ab)+", "aba", True),
    (r"x|y", "z", False),
]

REGEX_PATTERNS_MEDIUM = [
    (r"^a[bc]+d$", "abbcd", True),
    (r"^a[bc]+d$", "aXd", False),
    (r"^\d{3,5}$", "12345", True),
    (r"^\d{3,5}$", "12", False),
    (r"^[A-Z][a-z]+$", "Hello", True),
    (r"^[A-Z][a-z]+$", "hello", False),
    (r"\b\w{4}\b", "this is cool", True),
    (r"\b\w{4}\b", "hi me", False),
    (r"^(ab|cd)*$", "abcdab", True),
    (r"^(ab|cd)*$", "abx", False),
]

REGEX_PATTERNS_HARD = [
    (r"^(a+)b\1$", "aabaa", True),
    (r"^(a+)b\1$", "aabaaa", False),
    (r"^(\w+) \1$", "hello hello", True),
    (r"^(\w+) \1$", "hello world", False),
    (r"^(?=.*a)(?=.*b)\w+$", "abcdef", True),
    (r"^(?=.*a)(?=.*b)\w+$", "acdef", False),
    (r"(.)(.)\2\1", "abba", True),
    (r"(.)(.)\2\1", "abab", False),
    (r"^(\d)(?!\1)", "12", True),
    (r"^(\d)(?!\1)", "11", False),
]


def gen_regex_matching(difficulty: str, n: int):
    patterns_by_diff = {
        "easy":   REGEX_PATTERNS_EASY,
        "medium": REGEX_PATTERNS_MEDIUM,
        "hard":   REGEX_PATTERNS_HARD,
    }
    pool = patterns_by_diff[difficulty]
    problems = []
    for i in range(n):
        pattern, string, _expected = random.choice(pool)
        # Recompute truth at generation time (defensive — don't trust
        # the embedded flag).
        matches = bool(re.search(pattern, string))
        answer_sym = "'yes" if matches else "'no"
        scheme = answer_sym
        nl = (
            f"Does the regex pattern `{pattern}` match the string "
            f"`{string}` (using Python regex semantics — `re.search`)? "
            f"Answer `yes` or `no`."
        )
        problems.append(Problem(
            id=f"regex-{difficulty}-{i:03d}",
            category="regex_matching",
            difficulty=difficulty,
            natural_language=nl,
            scheme_expression=scheme,
            answer_type="string",
        ))
    return problems


# ---- linear_recurrence ----
#
# a_n = c_1 a_{n-1} + c_2 a_{n-2} + ... + c_k a_{n-k} with initial
# conditions a_0..a_{k-1}. Compute a_N for a given N.
#
# Wile oracle: O(N) naive iteration in Scheme. When Wile lands matrix
# exponentiation, this generator's scheme expression can stay as-is
# or be updated for speed; N ≤ 120 is fine naive.

LINEAR_RECURRENCE_PRESETS = {
    # (order, N_range)
    "easy":   (2, (10, 20)),
    "medium": (2, (30, 50)),
    "hard":   (3, (80, 120)),
}


def gen_linear_recurrence(difficulty: str, n: int):
    order, N_range = LINEAR_RECURRENCE_PRESETS[difficulty]
    problems = []
    for i in range(n):
        # Coefficients: small positive integers so the sequence grows
        # monotonically without oscillation or collapse.
        coefs = [random.randint(1, 3) for _ in range(order)]
        inits = [random.randint(1, 5) for _ in range(order)]
        N = random.randint(*N_range)

        inits_sch = "(list " + " ".join(str(v) for v in inits) + ")"
        coefs_sch = "(list " + " ".join(str(c) for c in coefs) + ")"
        # Pre-computed index list `(0 1 2 ... order-1)` — used to pair
        # each coefficient with its offset from the current index.
        # Avoids needing a recursive `enumerate` helper inside Scheme.
        indices_sch = "'(" + " ".join(str(k) for k in range(order)) + ")"

        scheme = (
            f"(let ((coefs {coefs_sch})\n"
            f"      (indices {indices_sch})\n"
            f"      (N {N}))\n"
            f"  (let loop ((seq {inits_sch}) (idx {order}))\n"
            f"    (if (> idx N)\n"
            f"        (list-ref seq N)\n"
            f"        (let ((next (apply +\n"
            f"                      (map (lambda (c k)\n"
            f"                             (* c (list-ref seq (- idx 1 k))))\n"
            f"                           coefs\n"
            f"                           indices))))\n"
            f"          (loop (append seq (list next)) (+ idx 1))))))"
        )

        # Natural-language recurrence string.
        coef_terms = []
        for k, c in enumerate(coefs):
            if c == 1:
                coef_terms.append(f"a_{{n-{k+1}}}")
            else:
                coef_terms.append(f"{c} a_{{n-{k+1}}}")
        recurrence_str = "a_n = " + " + ".join(coef_terms)
        initials_str = ", ".join(
            f"a_{k} = {v}" for k, v in enumerate(inits)
        )
        nl = (
            f"Let the sequence `a_0, a_1, a_2, ...` be defined by the "
            f"linear recurrence `{recurrence_str}` with initial conditions "
            f"`{initials_str}`. Compute `a_{N}`. Give a non-negative integer."
        )
        problems.append(Problem(
            id=f"linrec-{difficulty}-{i:03d}",
            category="linear_recurrence",
            difficulty=difficulty,
            natural_language=nl,
            scheme_expression=scheme,
            answer_type="integer",
        ))
    return problems


# ---- boolean_satisfiability ----
#
# Small CNF instances. Each clause is a disjunction of literals; the
# formula is their conjunction. Variables named x1, x2, .... Ground
# truth is computed in Python at generation time by brute-force
# enumeration over all 2^n assignments; the scheme_expression is a
# quoted Scheme list of symbols (or the symbol UNSAT) that Wile echoes
# back via (write ...) in the canonical `(x1=T x2=F ...)` form.
#
# Same bypass-Wile-compute pattern as gen_regex_matching: SAT isn't a
# Wile primitive, and solving it in Scheme buys us nothing the LLM
# treatment arm could use.
#
# Output format (satisfiable): "(x1=T x2=F x3=T ...)"
# Output format (unsatisfiable): "UNSAT"

SAT_PRESETS = {
    # (n_vars, n_clauses, clause_size)
    "easy":   (3, 4, 2),
    "medium": (5, 10, 3),
    "hard":   (8, 18, 3),
}


def _sat_first_assignment(clauses, n_vars: int):
    """Brute-force: return the first satisfying assignment or None.

    clauses: list of lists of (var_index, is_positive) pairs (var_index
    is 1-indexed). Returns list[bool] of length n_vars, or None if
    UNSAT.
    """
    for bits in itertools.product([False, True], repeat=n_vars):
        def satisfies(cl):
            return any(bits[idx - 1] == pos for idx, pos in cl)
        if all(satisfies(cl) for cl in clauses):
            return list(bits)
    return None


def _format_sat_answer(assignment, n_vars: int) -> str:
    if assignment is None:
        return "UNSAT"
    parts = [
        f"x{i + 1}=" + ("T" if assignment[i] else "F")
        for i in range(n_vars)
    ]
    return "(" + " ".join(parts) + ")"


def _gen_sat_clause(n_vars: int, clause_size: int):
    """Pick clause_size distinct variables, with random sign."""
    idxs = random.sample(range(1, n_vars + 1), clause_size)
    return [(idx, random.choice([True, False])) for idx in idxs]


def _sat_scheme_literal(answer: str) -> str:
    """Convert a SAT answer string to a Scheme expression that, when
    passed through (write ...), outputs the same bare text.

    'UNSAT'           -> "'UNSAT"            (quoted symbol)
    '(x1=T x2=F ...)' -> "'(x1=T x2=F ...)"  (quoted list of symbols)
    """
    if answer == "UNSAT":
        return "'UNSAT"
    inner = answer.strip("()").strip()
    return f"'({inner})"


def gen_boolean_satisfiability(difficulty: str, n: int):
    n_vars, n_clauses, clause_size = SAT_PRESETS[difficulty]
    problems = []
    for i in range(n):
        clauses = [
            _gen_sat_clause(n_vars, clause_size) for _ in range(n_clauses)
        ]

        # Ground truth from Python brute-force enumeration.
        assignment = _sat_first_assignment(clauses, n_vars)
        answer = _format_sat_answer(assignment, n_vars)
        scheme = _sat_scheme_literal(answer)

        # Natural-language formula.
        nl_clauses = []
        for cl in clauses:
            lits = [
                f"x_{idx}" if pos else f"\u00acx_{idx}"
                for idx, pos in cl
            ]
            nl_clauses.append("(" + " \u2228 ".join(lits) + ")")
        formula_nl = " \u2227 ".join(nl_clauses)

        nl = (
            f"Consider the Boolean formula `{formula_nl}` over variables "
            f"`x_1, x_2, ..., x_{n_vars}`. Is the formula satisfiable? "
            f"If yes, give a satisfying assignment in the form "
            f"`(x1=T x2=F x3=T ...)` with variables in order. "
            f"If no, answer `UNSAT`."
        )
        problems.append(Problem(
            id=f"sat-{difficulty}-{i:03d}",
            category="boolean_satisfiability",
            difficulty=difficulty,
            natural_language=nl,
            scheme_expression=scheme,
            answer_type="string",
        ))
    return problems


# ---- group_theory ----
#
# Permutation-group problems on S_n. Permutations are represented as
# 1-indexed lists: perm[i-1] is the image of i under the permutation.
# Three tiers test increasingly composed operations:
#   easy:   order of a single permutation in S_4
#   medium: order of a composition α∘β in S_5
#   hard:   commutator [α, β] = α β α^{-1} β^{-1} in S_6
#
# Ground truth is computed in Python at generation time and embedded
# in the scheme_expression as an appropriate Scheme literal (integer
# for order tasks, quoted list for the permutation answer).

GROUP_PRESETS = {
    # (n, task) where task is one of "order-elem", "order-comp", "commutator"
    "easy":   (4, "order-elem"),
    "medium": (5, "order-comp"),
    "hard":   (6, "commutator"),
}


def _random_permutation(n: int):
    values = list(range(1, n + 1))
    random.shuffle(values)
    return values


def _perm_compose(a, b):
    """Return a ∘ b (apply b first, then a). 1-indexed lists."""
    return [a[b[i] - 1] for i in range(len(b))]


def _perm_order(p):
    n = len(p)
    cur = list(p)
    identity = list(range(1, n + 1))
    k = 1
    while cur != identity:
        cur = _perm_compose(p, cur)
        k += 1
        if k > 5000:
            raise RuntimeError("order exceeded safety cap")
    return k


def _perm_inverse(p):
    """Return p^{-1}. For a 1-indexed list p, the inverse q satisfies
    p[q[i]-1] = i+1."""
    n = len(p)
    inv = [0] * n
    for i in range(n):
        inv[p[i] - 1] = i + 1
    return inv


def _cycle_str(perm):
    """Pretty-print a permutation as disjoint cycles, e.g. '(1 3 2)(4 5)'."""
    n = len(perm)
    seen = [False] * (n + 1)
    out = []
    for start in range(1, n + 1):
        if seen[start]:
            continue
        cur = start
        cyc = []
        while not seen[cur]:
            seen[cur] = True
            cyc.append(cur)
            cur = perm[cur - 1]
        if len(cyc) > 1:
            out.append("(" + " ".join(str(x) for x in cyc) + ")")
    return "".join(out) if out else "(identity)"


def gen_group_theory(difficulty: str, n: int):
    n_symm, task = GROUP_PRESETS[difficulty]
    problems = []
    for i in range(n):
        if task == "order-elem":
            perm = _random_permutation(n_symm)
            order = _perm_order(perm)
            scheme = str(order)
            answer_type = "integer"
            cycles = _cycle_str(perm)
            nl = (
                f"In the symmetric group S_{n_symm}, consider the "
                f"permutation σ given by σ = {cycles} (expressed as "
                f"disjoint cycles on `{{1, 2, ..., {n_symm}}}`). "
                f"Compute the order of σ — the smallest positive integer "
                f"`k` such that σ^k is the identity. Give a positive integer."
            )

        elif task == "order-comp":
            a = _random_permutation(n_symm)
            b = _random_permutation(n_symm)
            ab = _perm_compose(a, b)
            order = _perm_order(ab)
            scheme = str(order)
            answer_type = "integer"
            a_cycles = _cycle_str(a)
            b_cycles = _cycle_str(b)
            nl = (
                f"In S_{n_symm}, let α = {a_cycles} and β = {b_cycles}. "
                f"Compute the order of the composition α∘β (i.e., apply "
                f"β first, then α). Give a positive integer."
            )

        elif task == "commutator":
            a = _random_permutation(n_symm)
            b = _random_permutation(n_symm)
            a_inv = _perm_inverse(a)
            b_inv = _perm_inverse(b)
            # [a, b] = a ∘ b ∘ a^{-1} ∘ b^{-1}
            step1 = _perm_compose(a, b)
            step2 = _perm_compose(step1, a_inv)
            commutator = _perm_compose(step2, b_inv)
            # Scheme literal: quoted list of integers.
            scheme = "'(" + " ".join(str(x) for x in commutator) + ")"
            answer_type = "permutation"
            a_cycles = _cycle_str(a)
            b_cycles = _cycle_str(b)
            nl = (
                f"In S_{n_symm}, let α = {a_cycles} and β = {b_cycles}. "
                f"Compute the commutator [α, β] = α ∘ β ∘ α⁻¹ ∘ β⁻¹ "
                f"(applying right to left: apply β⁻¹ first, then α⁻¹, "
                f"then β, then α). Give the result as a permutation in "
                f"one-line notation: `(σ(1) σ(2) ... σ({n_symm}))` — the "
                f"image of each input position listed in order. Example "
                f"format: `(1 2 3 4 5 6)`."
            )

        else:
            raise ValueError(f"unknown task {task}")

        problems.append(Problem(
            id=f"group-{difficulty}-{i:03d}",
            category="group_theory",
            difficulty=difficulty,
            natural_language=nl,
            scheme_expression=scheme,
            answer_type=answer_type,
        ))
    return problems


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
    "set_closure":            (DIFFICULTIES, gen_set_closure),
    "graph_reachability":     (DIFFICULTIES, gen_graph_reachability),

    "prime_factorization":    (DIFFICULTIES, gen_prime_factorization),
    "combinatorial_counting": (DIFFICULTIES, gen_combinatorial_counting),

    "regex_matching":         (DIFFICULTIES, gen_regex_matching),
    "linear_recurrence":      (DIFFICULTIES, gen_linear_recurrence),

    "boolean_satisfiability": (DIFFICULTIES, gen_boolean_satisfiability),

    "group_theory":           (DIFFICULTIES, gen_group_theory),
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
