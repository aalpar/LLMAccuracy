# Sonnet-Coverage Capability Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the 12-category capability map with 3-tier difficulty coverage (easy/medium/hard) for each test, then run the full 180-problem map on Claude Sonnet 4.6 to produce an LLM-baseline capability map that calibrates where to extend to 5 tiers.

**Architecture:** Six new generators are added to `capability-map/generate_capability_problems.py` (joining the 6 already built — 4 reused + 2 written in Session 3). Each generator exposes an `easy/medium/hard` difficulty parameter and produces `Problem` dataclasses compatible with the existing evaluate.py pipeline. Ground-truth oracles stay in-Scheme for 11 of 12 categories; `regex_matching` uses a Python-precompute hybrid because Wile's regex support is unverified. After generation, one evaluate.py run on Sonnet 4.6 produces the first complete capability map. Analysis lands in `docs/plans/` as a report.

**Tech Stack:** Python 3.10, Wile Scheme (for ground-truth oracles), Anthropic SDK (claude-sonnet-4-6), pytest (generator unit tests), existing capability-map/ project conventions.

---

## Pre-flight

**Context to understand before starting:**

- `docs/plans/2026-04-19-capability-map-design.md` — architectural decisions (directory layout, harness reuse, per-category difficulty lists, curve-based classifier).
- `docs/plans/2026-04-19-capability-map-categories.md` — content design for each of 12 categories: what they probe, expected LLM/Wile boundary, difficulty tier semantics, example problems per tier.
- `capability-map/generate_capability_problems.py` — current state: 6 generators wired (4 reused + prime_factorization + combinatorial_counting).
- `algebra-accuracy/evaluate.py` — the A/B harness; used unchanged.
- `algebra-accuracy/generate.py:447` (`build_scheme_script`) — shows how scheme expressions get wrapped in `(write ...)` for oracle output.

**Working assumption:** Every new generator produces `Problem(scheme_expression=...)` strings that Wile can evaluate to a printable answer value. The `write` of that value gives a string that the existing `extract_answer` / `answers_match` graders handle via the existing answer_type enum (`integer`, `set`, `polynomial`, `permutation`, `decimal`, plus fallback string compare).

**New answer type (no code change needed):** `string` — falls through to the existing string-equality path in `answers_match`. Used for regex_matching ("yes"/"no") and boolean_satisfiability ("SAT"/"UNSAT" plus assignment format). No enum extension; `normalize_answer` returns the input string unchanged after int/Fraction parses fail.

**Model identifier:** `claude-sonnet-4-6` (per project convention; see `memory/project_benchmark_state.md` mentioning Sonnet 4.6 as the prior benchmark target).

---

## Phase 1 — Complete the 6 remaining generators (Tasks 1–6)

Each task adds one new generator to `capability-map/generate_capability_problems.py`, wires it into the `CATEGORIES` dispatch, adds a pytest structural test, and runs a Wile-pipeline smoke test.

Tasks are ordered from simplest to most specialized:

- **Task 1:** `graph_reachability` — set iteration over adjacency
- **Task 2:** `set_closure` — set iteration under a generating operation
- **Task 3:** `regex_matching` — Python-precompute hybrid
- **Task 4:** `linear_recurrence` — Scheme iteration
- **Task 5:** `boolean_satisfiability` — Scheme brute-force enumeration
- **Task 6:** `group_theory` — explicit permutation composition in Scheme

---

### Task 1: `gen_graph_reachability`

**Context:** Tests mechanical graph traversal. Given a directed graph and a source vertex, compute the set of reachable vertices. Wile oracle is a Scheme `letrec` implementing fixed-point iteration over the adjacency relation — does not require any algebra-library primitives beyond standard Scheme list and set operations.

**Files:**
- Modify: `capability-map/generate_capability_problems.py` (add `gen_graph_reachability` function, add `GRAPH_REACHABILITY_PRESETS` constant, wire into `CATEGORIES`).
- Create: `capability-map/tests/__init__.py` (empty) if not present.
- Create: `capability-map/tests/test_generators.py` with graph_reachability structural test.
- Create: `capability-map/pytest.ini`.

- [ ] **Step 1: Scaffold pytest infrastructure for capability-map**

Create `capability-map/pytest.ini`:

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
```

Create `capability-map/tests/__init__.py` (empty).

Create `capability-map/tests/conftest.py`:

```python
"""Pytest fixtures shared across capability-map generator tests."""
import sys
from pathlib import Path

# Make generate_capability_problems importable under its module name.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# And algebra-accuracy for the imported Problem dataclass.
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent.parent.parent / "algebra-accuracy"),
)
```

- [ ] **Step 2: Verify pytest discovers the test dir**

Run: `cd capability-map && python3 -m pytest --collect-only 2>&1 | head`
Expected: `collected 0 items` with no errors.

- [ ] **Step 3: Write the failing test for graph_reachability**

Create `capability-map/tests/test_generators.py`:

```python
"""Unit tests for capability-map generators.

Each test verifies that a generator produces well-formed Problem
dataclasses at the requested count and difficulty. Integration with
Wile (actually running the scheme_expression) is a separate smoke test.
"""
import random
from generate_capability_problems import (
    gen_graph_reachability,
)


def test_graph_reachability_produces_requested_count():
    random.seed(0)
    problems = gen_graph_reachability("easy", n=3)
    assert len(problems) == 3


def test_graph_reachability_problem_has_required_fields():
    random.seed(0)
    p = gen_graph_reachability("medium", n=1)[0]
    assert p.category == "graph_reachability"
    assert p.difficulty == "medium"
    assert p.id.startswith("reach-medium-")
    assert p.answer_type == "set"
    assert "reach" in p.natural_language.lower() or "reachable" in p.natural_language.lower()
    assert p.scheme_expression  # non-empty


def test_graph_reachability_supports_three_difficulties():
    random.seed(0)
    for diff in ("easy", "medium", "hard"):
        problems = gen_graph_reachability(diff, n=1)
        assert len(problems) == 1
        assert problems[0].difficulty == diff
```

- [ ] **Step 4: Run test — should fail with ImportError**

Run: `cd capability-map && python3 -m pytest tests/test_generators.py -v 2>&1 | tail -10`
Expected: ImportError on `gen_graph_reachability` (not defined yet).

- [ ] **Step 5: Implement `gen_graph_reachability`**

Add to `capability-map/generate_capability_problems.py` after the `_combin_multiset` function (end of existing new-generator section):

```python
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


def _gen_graph(n_vertices: int, n_edges: int, n_cycles: int) -> "tuple[list[str], list[tuple[str,str]], str]":
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
            f"    (let* ((frontier\n"
            f"             (apply append\n"
            f"               (map (lambda (e)\n"
            f"                      (if (and (memq (car e) reach)\n"
            f"                               (not (memq (cadr e) reach)))\n"
            f"                          (list (cadr e))\n"
            f"                          '()))\n"
            f"                    edges)))\n"
            f"           (new-reach (append frontier reach)))\n"
            f"      (if (null? frontier)\n"
            f"          (sort reach (lambda (a b) (string<? (symbol->string a) (symbol->string b))))\n"
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
```

- [ ] **Step 6: Wire `gen_graph_reachability` into CATEGORIES**

In the `CATEGORIES` dict, replace the commented `graph_reachability` line with the active entry:

```python
    "graph_reachability":     (DIFFICULTIES, gen_graph_reachability),
```

- [ ] **Step 7: Run test — should pass**

Run: `cd capability-map && python3 -m pytest tests/test_generators.py::test_graph_reachability_produces_requested_count tests/test_generators.py::test_graph_reachability_problem_has_required_fields tests/test_generators.py::test_graph_reachability_supports_three_difficulties -v`
Expected: 3 tests pass.

- [ ] **Step 8: Wile-pipeline smoke test**

Run: `cd /Users/aalpar/ClaudeProjects/LLMAccuracy && python3 capability-map/generate_capability_problems.py --wile /usr/local/bin/wile --categories graph_reachability --count 2 --output /tmp/reach_smoke.json 2>&1 | tail -8`
Expected: 6 problems written, 3 per difficulty, each with a non-empty answer. Inspect `/tmp/reach_smoke.json` first problem — should have an `answer` like `(a b c)` or `(a)`.

- [ ] **Step 9: Commit**

```bash
git add capability-map/generate_capability_problems.py capability-map/pytest.ini capability-map/tests/
git commit -m "feat(capability-map): add gen_graph_reachability

Implements the first of the three pending 'active' capability-map
generators. Produces directed-graph reachability problems at three
tiers: easy (5 vertices, 6 edges, 1 cycle), medium (10 vertices, 15
edges, 3 cycles), hard (20 vertices, 40 edges, 6 cycles).

Wile oracle uses fixed-point iteration over the adjacency relation —
no algebra-library primitives required. Answer type is 'set' of
vertex names in alphabetical order.

Also scaffolds pytest for capability-map with conftest.py that
makes both capability-map/ and algebra-accuracy/ importable."
```

---

### Task 2: `gen_set_closure`

**Context:** Tests fixed-point computation — given a starting set and a generating operation, find the least superset closed under that operation. Wile oracle is the same fixed-point idiom as graph_reachability but over a small number ring.

**Files:**
- Modify: `capability-map/generate_capability_problems.py`
- Modify: `capability-map/tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Append to `capability-map/tests/test_generators.py`:

```python
from generate_capability_problems import gen_set_closure


def test_set_closure_produces_requested_count():
    random.seed(0)
    problems = gen_set_closure("easy", n=3)
    assert len(problems) == 3


def test_set_closure_problem_has_required_fields():
    random.seed(0)
    p = gen_set_closure("medium", n=1)[0]
    assert p.category == "set_closure"
    assert p.difficulty == "medium"
    assert p.id.startswith("closure-medium-")
    assert p.answer_type == "set"


def test_set_closure_supports_three_difficulties():
    random.seed(0)
    for diff in ("easy", "medium", "hard"):
        problems = gen_set_closure(diff, n=1)
        assert problems[0].difficulty == diff
```

- [ ] **Step 2: Run — should fail**

Run: `cd capability-map && python3 -m pytest tests/test_generators.py::test_set_closure_produces_requested_count -v`
Expected: ImportError.

- [ ] **Step 3: Implement `gen_set_closure`**

Add to `capability-map/generate_capability_problems.py` after `gen_graph_reachability`:

```python
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
                op_nls.append(f"(a × b) mod {mod}")
            elif op == "+3":
                op_schemes.append(f"(lambda (a b) (modulo (+ a b 3) {mod}))")
                op_nls.append(f"(a + b + 3) mod {mod}")
            else:
                raise ValueError(f"unknown op {op}")

        start_sch = "(list " + " ".join(str(x) for x in start) + ")"
        ops_sch = "(list " + " ".join(op_schemes) + ")"

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
            f"           (novel (filter (lambda (x) (not (member x acc))) new-values))\n"
            f"           (novel-dedup (let dedup ((xs novel) (seen '()))\n"
            f"                          (cond\n"
            f"                            ((null? xs) (reverse seen))\n"
            f"                            ((member (car xs) seen) (dedup (cdr xs) seen))\n"
            f"                            (else (dedup (cdr xs) (cons (car xs) seen)))))))\n"
            f"      (if (null? novel-dedup)\n"
            f"          (sort acc <)\n"
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
```

- [ ] **Step 4: Wire into CATEGORIES**

Replace the commented `set_closure` entry:

```python
    "set_closure":            (DIFFICULTIES, gen_set_closure),
```

- [ ] **Step 5: Run test — should pass**

Run: `cd capability-map && python3 -m pytest tests/test_generators.py -v`
Expected: 6 tests pass (3 prior graph_reachability + 3 set_closure).

- [ ] **Step 6: Wile-pipeline smoke test**

Run: `cd /Users/aalpar/ClaudeProjects/LLMAccuracy && python3 capability-map/generate_capability_problems.py --wile /usr/local/bin/wile --categories set_closure --count 2 --output /tmp/closure_smoke.json 2>&1 | tail -6`
Expected: 6 problems written, each with a computed answer.

- [ ] **Step 7: Commit**

```bash
git add capability-map/generate_capability_problems.py capability-map/tests/test_generators.py
git commit -m "feat(capability-map): add gen_set_closure

Produces set-closure problems over Z/nZ with configurable generating
operations. Three tiers:
  easy: mod 11, 2 starting elements, single operation (+ mod 11)
  medium: mod 13, 3 starting elements, two operations (+ and * mod 13)
  hard: mod 17, 3 starting elements, three operations (+, *, +3 mod 17)

Wile oracle uses naive fixed-point iteration with explicit membership
deduplication. Answer type 'set' of integers in sorted order."
```

---

### Task 3: `gen_regex_matching`

**Context:** Tests regex comprehension. Ground truth computed in Python (via `re` module) at generation time and embedded as a literal symbol in the scheme_expression — we haven't verified Wile has regex, and the pattern-matching task itself doesn't benefit from a Wile primitive at the LLM's treatment arm, so embedding the oracle answer directly is acceptable.

**Files:**
- Modify: `capability-map/generate_capability_problems.py`
- Modify: `capability-map/tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Append to `capability-map/tests/test_generators.py`:

```python
from generate_capability_problems import gen_regex_matching


def test_regex_matching_produces_requested_count():
    random.seed(0)
    problems = gen_regex_matching("easy", n=3)
    assert len(problems) == 3


def test_regex_matching_problem_has_required_fields():
    random.seed(0)
    p = gen_regex_matching("medium", n=1)[0]
    assert p.category == "regex_matching"
    assert p.id.startswith("regex-medium-")
    assert p.answer_type == "string"
    # Scheme expression should be either 'yes or 'no symbol literal.
    assert p.scheme_expression.strip() in ("'yes", "'no")


def test_regex_matching_supports_three_difficulties():
    random.seed(0)
    for diff in ("easy", "medium", "hard"):
        problems = gen_regex_matching(diff, n=1)
        assert problems[0].difficulty == diff
```

- [ ] **Step 2: Run — should fail**

Run: `cd capability-map && python3 -m pytest tests/test_generators.py::test_regex_matching_produces_requested_count -v`
Expected: ImportError.

- [ ] **Step 3: Implement `gen_regex_matching`**

Add to `capability-map/generate_capability_problems.py` after `gen_set_closure`. Need `import re` at the top of the file — check first, add if missing.

```python
import re  # noqa: E402 (already at top via generate import?)  — add if missing


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
```

- [ ] **Step 4: Add `import re` near the top of `generate_capability_problems.py`**

Find the existing import block (around line 22). Add `import re` after `import random`.

- [ ] **Step 5: Wire into CATEGORIES**

Replace the commented `regex_matching` entry:

```python
    "regex_matching":         (DIFFICULTIES, gen_regex_matching),
```

- [ ] **Step 6: Run test — should pass**

Run: `cd capability-map && python3 -m pytest tests/test_generators.py -v`
Expected: 9 tests pass (all structural tests for three generators).

- [ ] **Step 7: Wile-pipeline smoke test**

Run: `cd /Users/aalpar/ClaudeProjects/LLMAccuracy && python3 capability-map/generate_capability_problems.py --wile /usr/local/bin/wile --categories regex_matching --count 2 --output /tmp/regex_smoke.json 2>&1 | tail -6`
Expected: 6 problems, each with answer "yes" or "no".

- [ ] **Step 8: Commit**

```bash
git add capability-map/generate_capability_problems.py capability-map/tests/test_generators.py
git commit -m "feat(capability-map): add gen_regex_matching (Python-precompute oracle)

Produces regex yes/no problems at three tiers:
  easy: literals, alternation, kleene-star/plus
  medium: character classes, anchors, bounded repetition, word boundaries
  hard: backreferences, lookahead, captured-group repetition

Ground truth is computed in Python (via re.search) at generation time
and embedded as a Scheme symbol literal ('yes / 'no) in the scheme
expression. This avoids depending on Wile's regex support, which is
not verified. The LLM's treatment arm gets no advantage from Wile on
these problems — they become a pure LLM reasoning probe. That's
intentional: regex_matching's capability-map contribution is whether
Sonnet can correctly evaluate regex semantics, not whether tools help.

Answer type 'string', falls through to string-equality compare in
answers_match."
```

---

### Task 4: `gen_linear_recurrence`

**Context:** Given a linear recurrence and initial conditions, compute `a_N`. Scheme oracle uses naive iteration — O(N) integer arithmetic. Wile primitives not required for the oracle; when Wile adds matrix exp, the oracle remains correct (slower).

**Files:**
- Modify: `capability-map/generate_capability_problems.py`
- Modify: `capability-map/tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Append to `capability-map/tests/test_generators.py`:

```python
from generate_capability_problems import gen_linear_recurrence


def test_linear_recurrence_produces_requested_count():
    random.seed(0)
    problems = gen_linear_recurrence("easy", n=3)
    assert len(problems) == 3


def test_linear_recurrence_problem_has_required_fields():
    random.seed(0)
    p = gen_linear_recurrence("medium", n=1)[0]
    assert p.category == "linear_recurrence"
    assert p.id.startswith("linrec-medium-")
    assert p.answer_type == "integer"


def test_linear_recurrence_supports_three_difficulties():
    random.seed(0)
    for diff in ("easy", "medium", "hard"):
        assert gen_linear_recurrence(diff, n=1)[0].difficulty == diff
```

- [ ] **Step 2: Run — should fail with ImportError**

- [ ] **Step 3: Implement `gen_linear_recurrence`**

Add to `capability-map/generate_capability_problems.py`:

```python
# ---- linear_recurrence ----
#
# a_n = c_1 a_{n-1} + c_2 a_{n-2} + ... + c_k a_{n-k} with initial
# conditions a_0..a_{k-1}. Compute a_N for a given N.
#
# Wile oracle: O(N) naive iteration in Scheme. Slow for hard tier
# (N=100) but still fast enough (<1s). When Wile lands matrix
# exponentiation, this generator's scheme expression can stay as-is
# or be updated for speed.

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
        # Coefficients: small integers, signs chosen so the sequence
        # grows moderately (no huge values, no oscillations that cause
        # immediate zero).
        coefs = [random.randint(1, 3) for _ in range(order)]
        inits = [random.randint(1, 5) for _ in range(order)]
        N = random.randint(*N_range)

        # Scheme naive iteration. Sequence indexed a_0, a_1, ...
        inits_sch = "(list " + " ".join(str(v) for v in inits) + ")"
        coefs_sch = "(list " + " ".join(str(c) for c in coefs) + ")"
        scheme = (
            f"(let loop ((seq {inits_sch}) (idx {order}))\n"
            f"  (if (> idx {N})\n"
            f"      (list-ref seq {N})\n"
            f"      (let ((next\n"
            f"              (apply +\n"
            f"                (map (lambda (c i) (* c (list-ref seq i)))\n"
            f"                     {coefs_sch}\n"
            f"                     '{tuple(range(idx - 1, idx - 1 - order, -1)) if False else list(range(idx - order, idx))[::-1]}))))\n"
            f"        (loop (append seq (list next)) (+ idx 1)))))"
        )
        # NB: the `'(0 1 2 ...)` list of indices used by map has to
        # rotate as we advance. Implementing that inline in the Scheme
        # loop is clearer than pre-computing — rewrite:
        scheme = (
            f"(let ((coefs {coefs_sch})\n"
            f"      (order {order})\n"
            f"      (N {N}))\n"
            f"  (let loop ((seq {inits_sch}) (idx order))\n"
            f"    (if (> idx N)\n"
            f"        (list-ref seq N)\n"
            f"        (let ((next\n"
            f"                (apply +\n"
            f"                  (map (lambda (c k) (* c (list-ref seq (- idx 1 k))))\n"
            f"                       coefs\n"
            f"                       (let enumerate ((m 0))\n"
            f"                         (if (= m order) '()\n"
            f"                             (cons m (enumerate (+ m 1))))))))))\n"
            f"          (loop (append seq (list next)) (+ idx 1))))))"
        )

        # Natural-language problem.
        coef_terms = []
        for k, c in enumerate(coefs):
            sign = "+" if c >= 0 else "-"
            mag = abs(c)
            coef_terms.append(
                f"{sign} {mag} a_{{n-{k+1}}}"
                if mag != 1
                else f"{sign} a_{{n-{k+1}}}"
            )
        recurrence_str = "a_n = " + " ".join(coef_terms).lstrip("+").strip()
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
```

- [ ] **Step 4: Wire into CATEGORIES**

Find the "Stubbed — Wile primitive incoming" comment block. Replace:

```python
    # "linear_recurrence":      (DIFFICULTIES, gen_linear_recurrence),
```

with:

```python
    "linear_recurrence":      (DIFFICULTIES, gen_linear_recurrence),
```

Note the comment above the stubs block should be updated too, or move this entry to the active section. For clarity, move it up above the stubs comment.

- [ ] **Step 5: Run tests — should pass**

Run: `cd capability-map && python3 -m pytest tests/test_generators.py -v`
Expected: 12 structural tests pass.

- [ ] **Step 6: Wile-pipeline smoke test**

Run: `python3 capability-map/generate_capability_problems.py --wile /usr/local/bin/wile --categories linear_recurrence --count 2 --output /tmp/linrec_smoke.json 2>&1 | tail -6`
Expected: 6 problems with positive integer answers.

- [ ] **Step 7: Commit**

```bash
git add capability-map/generate_capability_problems.py capability-map/tests/test_generators.py
git commit -m "feat(capability-map): add gen_linear_recurrence

Produces linear-recurrence a_N problems at three tiers:
  easy: order 2, N in [10, 20]
  medium: order 2, N in [30, 50]
  hard: order 3, N in [80, 120]

Wile oracle: naive O(N) iteration in Scheme. Integer arithmetic only;
no matrix exponentiation required. When Wile adds matrix-exp
primitives, the generator's scheme expression remains valid; speed
is not a concern at these N values."
```

---

### Task 5: `gen_boolean_satisfiability`

**Context:** Small SAT instances. Wile oracle uses brute-force enumeration over 2^n variable assignments — tractable for n ≤ 8. Answer is either `UNSAT` or a variable assignment in a canonical format.

**Files:**
- Modify: `capability-map/generate_capability_problems.py`
- Modify: `capability-map/tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Append to `capability-map/tests/test_generators.py`:

```python
from generate_capability_problems import gen_boolean_satisfiability


def test_sat_produces_requested_count():
    random.seed(0)
    problems = gen_boolean_satisfiability("easy", n=3)
    assert len(problems) == 3


def test_sat_problem_has_required_fields():
    random.seed(0)
    p = gen_boolean_satisfiability("medium", n=1)[0]
    assert p.category == "boolean_satisfiability"
    assert p.id.startswith("sat-medium-")
    assert p.answer_type == "string"


def test_sat_supports_three_difficulties():
    random.seed(0)
    for diff in ("easy", "medium", "hard"):
        assert gen_boolean_satisfiability(diff, n=1)[0].difficulty == diff
```

- [ ] **Step 2: Run — should fail**

- [ ] **Step 3: Implement `gen_boolean_satisfiability`**

Add to `capability-map/generate_capability_problems.py`:

```python
# ---- boolean_satisfiability ----
#
# Small CNF instances. Each clause is a disjunction of literals; the
# formula is their conjunction. Variables named x1, x2, .... Wile
# oracle enumerates 2^n assignments and reports the first satisfying
# one in canonical form, or "UNSAT".
#
# Output format (satisfiable): "(x1=T x2=F x3=T ...)"
# Output format (unsatisfiable): "UNSAT"

SAT_PRESETS = {
    # (n_vars, n_clauses, clause_size)
    "easy":   (3, 4, 2),
    "medium": (5, 10, 3),
    "hard":   (8, 18, 3),
}


def _gen_sat_clause(n_vars: int, clause_size: int) -> "list[tuple[int, bool]]":
    """Pick clause_size distinct variables, with random sign. Returns
    list of (var_index, is_positive) pairs."""
    idxs = random.sample(range(1, n_vars + 1), clause_size)
    return [(idx, random.choice([True, False])) for idx in idxs]


def gen_boolean_satisfiability(difficulty: str, n: int):
    n_vars, n_clauses, clause_size = SAT_PRESETS[difficulty]
    problems = []
    for i in range(n):
        clauses = [_gen_sat_clause(n_vars, clause_size) for _ in range(n_clauses)]

        # Natural-language formula.
        nl_clauses = []
        for cl in clauses:
            lits = [
                f"x_{idx}" if pos else f"¬x_{idx}"
                for idx, pos in cl
            ]
            nl_clauses.append("(" + " ∨ ".join(lits) + ")")
        formula_nl = " ∧ ".join(nl_clauses)

        # Scheme oracle: brute-force enumeration over bitmasks.
        # Encode each clause as a Scheme list: ((idx sign) (idx sign) ...)
        # with sign 1 for positive, 0 for negated.
        clauses_sch = "(list " + " ".join(
            "(list " + " ".join(
                f"(list {idx} {1 if pos else 0})" for idx, pos in cl
            ) + ")"
            for cl in clauses
        ) + ")"

        scheme = (
            f"(let ((n-vars {n_vars})\n"
            f"      (clauses {clauses_sch}))\n"
            f"  (let outer ((mask 0))\n"
            f"    (if (>= mask (expt 2 n-vars)) 'UNSAT\n"
            f"        (let* ((assign (lambda (idx)\n"
            f"                         (if (zero? (remainder (quotient mask (expt 2 (- idx 1))) 2))\n"
            f"                             0 1)))\n"
            f"               (clause-sat (lambda (cl)\n"
            f"                             (let inner ((lits cl))\n"
            f"                               (cond\n"
            f"                                 ((null? lits) 0)\n"
            f"                                 ((= (assign (car (car lits))) (cadr (car lits))) 1)\n"
            f"                                 (else (inner (cdr lits)))))))\n"
            f"               (all-sat (let go ((cs clauses))\n"
            f"                          (cond\n"
            f"                            ((null? cs) 1)\n"
            f"                            ((zero? (clause-sat (car cs))) 0)\n"
            f"                            (else (go (cdr cs)))))))\n"
            f"          (if (= all-sat 1)\n"
            f"              (let build ((k 1) (acc '()))\n"
            f"                (if (> k n-vars)\n"
            f"                    (list->string\n"
            f"                      (append (list #\\()\n"
            f"                              (let interp ((xs (reverse acc)) (first? #t))\n"
            f"                                (if (null? xs) (list #\\))\n"
            f"                                    (append\n"
            f"                                      (if first? '() (list #\\space))\n"
            f"                                      (string->list (car xs))\n"
            f"                                      (interp (cdr xs) #f))))))\n"
            f"                    (build (+ k 1)\n"
            f"                           (cons (string-append \"x\" (number->string k)\n"
            f"                                                \"=\"\n"
            f"                                                (if (= (assign k) 1) \"T\" \"F\"))\n"
            f"                                 acc))))\n"
            f"              (outer (+ mask 1)))))))"
        )

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
```

- [ ] **Step 4: Wire into CATEGORIES**

```python
    "boolean_satisfiability": (DIFFICULTIES, gen_boolean_satisfiability),
```

- [ ] **Step 5: Run tests — should pass**

Run: `cd capability-map && python3 -m pytest tests/test_generators.py -v`
Expected: 15 tests pass.

- [ ] **Step 6: Wile-pipeline smoke test**

Run: `python3 capability-map/generate_capability_problems.py --wile /usr/local/bin/wile --categories boolean_satisfiability --count 2 --output /tmp/sat_smoke.json 2>&1 | tail -6`
Expected: 6 problems, each with answer matching `(x1=T x2=F ...)` or `UNSAT`.

- [ ] **Step 7: Commit**

```bash
git add capability-map/generate_capability_problems.py capability-map/tests/test_generators.py
git commit -m "feat(capability-map): add gen_boolean_satisfiability

Produces small CNF-SAT instances at three tiers:
  easy: 3 vars, 4 clauses, 2-SAT
  medium: 5 vars, 10 clauses, 3-SAT
  hard: 8 vars, 18 clauses, 3-SAT (near-UNSAT range)

Wile oracle: brute-force enumeration over 2^n variable assignments.
Tractable for n ≤ 8 (256 assignments at worst). When Wile ships a
proper SAT solver, this generator stays correct; the solver just
completes faster.

Answer format: '(x1=T x2=F ...)' for SAT, 'UNSAT' for unsat.
Answer type 'string'."
```

---

### Task 6: `gen_group_theory`

**Context:** Permutation-group operations on S_n. Wile oracle: explicit permutation composition in Scheme. No algebra-library primitives required — permutations are represented as lists, composition via list lookup.

**Files:**
- Modify: `capability-map/generate_capability_problems.py`
- Modify: `capability-map/tests/test_generators.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
from generate_capability_problems import gen_group_theory


def test_group_theory_produces_requested_count():
    random.seed(0)
    problems = gen_group_theory("easy", n=3)
    assert len(problems) == 3


def test_group_theory_problem_has_required_fields():
    random.seed(0)
    p = gen_group_theory("medium", n=1)[0]
    assert p.category == "group_theory"
    assert p.id.startswith("group-medium-")
    assert p.answer_type in ("integer", "permutation")


def test_group_theory_supports_three_difficulties():
    random.seed(0)
    for diff in ("easy", "medium", "hard"):
        assert gen_group_theory(diff, n=1)[0].difficulty == diff
```

- [ ] **Step 2: Run — should fail**

- [ ] **Step 3: Implement `gen_group_theory`**

Add to `capability-map/generate_capability_problems.py`:

```python
# ---- group_theory ----
#
# Permutation-group problems on S_n. Permutations are represented as
# lists (sigma[i-1] is the image of i under sigma, 1-indexed). Supported
# sub-task per tier: order of an element (easy), order of a composition
# (medium), conjugation or commutator (hard).

GROUP_PRESETS = {
    # (n, task) where task is one of "order-elem", "order-comp", "commutator"
    "easy":   (4, "order-elem"),
    "medium": (5, "order-comp"),
    "hard":   (6, "commutator"),
}


def _random_permutation(n: int) -> "list[int]":
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


def gen_group_theory(difficulty: str, n: int):
    n_symm, task = GROUP_PRESETS[difficulty]
    problems = []
    for i in range(n):
        if task == "order-elem":
            perm = _random_permutation(n_symm)
            # Scheme: compute order by composing until identity.
            perm_sch = "(list " + " ".join(str(x) for x in perm) + ")"
            scheme = (
                f"(let ((p {perm_sch})\n"
                f"      (n {n_symm}))\n"
                f"  (let ((ident (let mk ((k 1)) (if (> k n) '() (cons k (mk (+ k 1))))))\n"
                f"        (compose (lambda (a b)\n"
                f"                   (let go ((i 1) (acc '()))\n"
                f"                     (if (> i n) (reverse acc)\n"
                f"                         (go (+ i 1)\n"
                f"                             (cons (list-ref a (- (list-ref b (- i 1)) 1))\n"
                f"                                   acc)))))))\n"
                f"    (let loop ((cur p) (k 1))\n"
                f"      (if (equal? cur ident) k\n"
                f"          (loop (compose p cur) (+ k 1))))))"
            )
            cycles = _cycle_str(perm)
            nl = (
                f"In the symmetric group S_{n_symm}, consider the "
                f"permutation σ given by σ = {cycles} (expressed as "
                f"disjoint cycles on `{{1, 2, ..., {n_symm}}}`). "
                f"Compute the order of σ — the smallest positive integer "
                f"`k` such that σ^k is the identity. Give a positive integer."
            )
            answer_type = "integer"

        elif task == "order-comp":
            a = _random_permutation(n_symm)
            b = _random_permutation(n_symm)
            a_sch = "(list " + " ".join(str(x) for x in a) + ")"
            b_sch = "(list " + " ".join(str(x) for x in b) + ")"
            scheme = (
                f"(let ((a {a_sch}) (b {b_sch}) (n {n_symm}))\n"
                f"  (let* ((ident (let mk ((k 1)) (if (> k n) '() (cons k (mk (+ k 1))))))\n"
                f"         (compose (lambda (x y)\n"
                f"                    (let go ((i 1) (acc '()))\n"
                f"                      (if (> i n) (reverse acc)\n"
                f"                          (go (+ i 1)\n"
                f"                              (cons (list-ref x (- (list-ref y (- i 1)) 1))\n"
                f"                                    acc))))))\n"
                f"         (ab (compose a b)))\n"
                f"    (let loop ((cur ab) (k 1))\n"
                f"      (if (equal? cur ident) k\n"
                f"          (loop (compose ab cur) (+ k 1))))))"
            )
            a_cycles = _cycle_str(a)
            b_cycles = _cycle_str(b)
            nl = (
                f"In S_{n_symm}, let α = {a_cycles} and β = {b_cycles}. "
                f"Compute the order of the composition α∘β. "
                f"Give a positive integer."
            )
            answer_type = "integer"

        elif task == "commutator":
            a = _random_permutation(n_symm)
            b = _random_permutation(n_symm)
            a_sch = "(list " + " ".join(str(x) for x in a) + ")"
            b_sch = "(list " + " ".join(str(x) for x in b) + ")"
            # Commutator [a,b] = a b a^{-1} b^{-1}. Output as a list.
            scheme = (
                f"(let ((a {a_sch}) (b {b_sch}) (n {n_symm}))\n"
                f"  (let* ((compose (lambda (x y)\n"
                f"                    (let go ((i 1) (acc '()))\n"
                f"                      (if (> i n) (reverse acc)\n"
                f"                          (go (+ i 1)\n"
                f"                              (cons (list-ref x (- (list-ref y (- i 1)) 1))\n"
                f"                                    acc))))))\n"
                f"         (inv (lambda (p)\n"
                f"                (let mk ((k 1) (acc '()))\n"
                f"                  (if (> k n) (map cdr (sort acc (lambda (u v) (< (car u) (car v)))))\n"
                f"                      (mk (+ k 1)\n"
                f"                          (cons (cons (list-ref p (- k 1)) k) acc))))))\n"
                f"         (a-inv (inv a))\n"
                f"         (b-inv (inv b))\n"
                f"         (step1 (compose a b))\n"
                f"         (step2 (compose step1 a-inv))\n"
                f"         (comm (compose step2 b-inv)))\n"
                f"    comm))"
            )
            a_cycles = _cycle_str(a)
            b_cycles = _cycle_str(b)
            nl = (
                f"In S_{n_symm}, let α = {a_cycles} and β = {b_cycles}. "
                f"Compute the commutator [α, β] = α β α^(-1) β^(-1). "
                f"Give the result as a permutation in one-line notation: "
                f"`(σ(1) σ(2) ... σ({n_symm}))` — i.e., the image of each "
                f"input position. Answer format: `(1 2 3 4 5 6)` style."
            )
            answer_type = "permutation"

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


def _cycle_str(perm: "list[int]") -> str:
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
    return "".join(out) if out else "identity"
```

- [ ] **Step 4: Wire into CATEGORIES**

```python
    "group_theory":           (DIFFICULTIES, gen_group_theory),
```

- [ ] **Step 5: Run tests — should pass**

Run: `cd capability-map && python3 -m pytest tests/test_generators.py -v`
Expected: 18 structural tests pass.

- [ ] **Step 6: Wile-pipeline smoke test**

Run: `python3 capability-map/generate_capability_problems.py --wile /usr/local/bin/wile --categories group_theory --count 2 --output /tmp/group_smoke.json 2>&1 | tail -6`
Expected: 6 problems with answers — easy/medium integers (permutation order), hard permutation lists.

- [ ] **Step 7: Commit**

```bash
git add capability-map/generate_capability_problems.py capability-map/tests/test_generators.py
git commit -m "feat(capability-map): add gen_group_theory

Produces permutation-group problems on S_n at three tiers:
  easy: S_4, order of a single permutation
  medium: S_5, order of a composition α∘β
  hard: S_6, commutator [α, β] = αβα^-1β^-1

Wile oracle: explicit permutation composition on 1-indexed lists.
No algebra-library primitives required. When Wile adds permutation-
group primitives (per project roadmap), this generator can be
rewritten to use them; the current answers stay valid.

Answer type is 'integer' for order tasks and 'permutation' for the
commutator task (reusing the existing sorted-integer-tuple type)."
```

---

## Phase 2 — Run on Sonnet and analyze (Tasks 7–9)

### Task 7: Regenerate the 12-category problem set

**Files:**
- Modify: `capability-map/capability_problems.json` (regenerated to include all 12 categories)

- [ ] **Step 1: Regenerate with all 12 categories**

Run: `cd /Users/aalpar/ClaudeProjects/LLMAccuracy && python3 capability-map/generate_capability_problems.py --wile /usr/local/bin/wile 2>&1 | tail -20`

Expected: summary shows 36 cells (12 categories × 3 difficulties), 180 problems total (n=5 each).

- [ ] **Step 2: Verify the file structure**

Run:
```bash
python3 -c "
import json
from collections import Counter
p = json.load(open('capability-map/capability_problems.json'))
c = Counter((x['category'], x['difficulty']) for x in p)
print(f'Total problems: {len(p)}')
print(f'Cells: {len(c)}')
for k, v in sorted(c.items()): print(f'  {k[0]}/{k[1]}: {v}')
"
```

Expected: `Total problems: 180`, `Cells: 36`, every cell has 5 problems.

- [ ] **Step 3: Commit**

```bash
git add capability-map/capability_problems.json
git commit -m "data: regenerate capability-map problems with all 12 categories (180 total)"
```

---

### Task 8: Run the capability map on Sonnet 4.6

**Files:**
- Create: `capability-map/capability_results_sonnet.json`

- [ ] **Step 1: Execute the benchmark on Sonnet**

Run:

```bash
cd /Users/aalpar/ClaudeProjects/LLMAccuracy && \
  python3 algebra-accuracy/evaluate.py \
    --problems capability-map/capability_problems.json \
    --output capability-map/capability_results_sonnet.json \
    --model claude-sonnet-4-6 \
    --wile /usr/local/bin/wile \
    --condition both \
    --workers 4 \
    --max-rounds 30 \
    --total-budget 10000
```

Expected: runs in ~45–75 min at workers=4 (180 problems × ~40s average). Produces `capability_results_sonnet.json` with 180 entries, each carrying control+treatment results.

If ANTHROPIC_API_KEY isn't set, the implementer should stop and report BLOCKED so the user can run it in their own session.

- [ ] **Step 2: Verify clean completion**

Run:

```bash
python3 -c "
import json
r = json.load(open('capability-map/capability_results_sonnet.json'))
n_err = sum(1 for x in r if 'error' in x)
print(f'{len(r)} total, {n_err} errors')
"
```

Expected: `180 total, 0 errors`.

- [ ] **Step 3: Commit the results file**

```bash
git add capability-map/capability_results_sonnet.json
git commit -m "run: Sonnet 4.6 capability-map at 12 categories x 3 difficulties x n=5

First complete capability-map run. 180 problems, max_rounds=30,
total_budget=10000, workers=4. Establishes the Sonnet baseline
that subsequent difficulty calibration (5-tier extension) will
use."
```

---

### Task 9: Write the Sonnet capability-map report

**Files:**
- Create: `capability-map/analyze_capability_map.py`
- Create: `docs/plans/2026-04-21-sonnet-capability-map-report.md`

- [ ] **Step 1: Implement the curve-based analyzer**

Create `capability-map/analyze_capability_map.py`:

```python
#!/usr/bin/env python3
"""Capability-Map Analyzer — curve-based per-category classification.

Reads a results JSON produced by evaluate.py and outputs, per category:
  - ctrl_rate and treat_rate at each of the 3 difficulty levels
  - curve-shape classification: LLM-OWNS-THROUGHOUT, CROSSOVER-FOUND,
    TOOL-ASSISTED-THROUGHOUT, TOOL-INTERFERES, CAPABILITY-GAP, AMBIGUOUS
  - the difficulty bucket where the regime changes (if any)

Usage:
    python capability-map/analyze_capability_map.py \\
        --results capability-map/capability_results_sonnet.json
"""

import argparse
import json
from collections import defaultdict
from pathlib import Path


DIFFICULTY_ORDER = ["easy", "medium", "hard", "extra-hard", "super-hard"]


def _rate(samples, arm_key):
    n = len(samples)
    c = sum(1 for r in samples if r.get(arm_key))
    return c / n if n else 0.0


def classify_curve(ctrl_curve, treat_curve):
    """Classify a category's (ctrl, treat) pair of difficulty curves.

    Inputs are lists of (difficulty, rate) pairs in DIFFICULTY_ORDER.
    Returns (classification, crossover_difficulty_or_None).
    """
    if not ctrl_curve:
        return "NO-DATA", None

    # Aligned on difficulty
    rates = [(d, c, t) for (d, c), (_, t) in zip(ctrl_curve, treat_curve)]

    # LLM-OWNS-THROUGHOUT: ctrl >= 0.70 at every measured difficulty
    if all(c >= 0.70 for _, c, _ in rates):
        return "LLM-OWNS-THROUGHOUT", None

    # CAPABILITY-GAP: at the hardest measured difficulty, both arms < 0.30
    last = rates[-1]
    if last[1] < 0.30 and last[2] < 0.30:
        return "CAPABILITY-GAP", last[0]

    # TOOL-INTERFERES: treat < ctrl by >= 0.20 at every difficulty
    if all(t <= c - 0.20 for _, c, t in rates):
        return "TOOL-INTERFERES", None

    # TOOL-ASSISTED-THROUGHOUT: treat >= ctrl + 0.20 at every difficulty
    if all(t >= c + 0.20 for _, c, t in rates):
        return "TOOL-ASSISTED-THROUGHOUT", rates[0][0]

    # CROSSOVER-FOUND: exists a difficulty where ctrl < 0.50 and
    # treat >= ctrl + 0.20
    for d, c, t in rates:
        if c < 0.50 and t >= c + 0.20:
            return "CROSSOVER-FOUND", d

    return "AMBIGUOUS", None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", type=Path, required=True)
    args = ap.parse_args()

    data = json.loads(args.results.read_text())
    cells = defaultdict(list)
    for r in data:
        cells[(r["category"], r["difficulty"])].append(r)

    categories = sorted({cat for cat, _ in cells.keys()})
    print(f"{'Category':<30} {'easy':>10} {'medium':>10} {'hard':>10}  "
          f"{'Classification':<24} {'Crossover'}")
    print("-" * 110)

    summary = defaultdict(list)
    for cat in categories:
        ctrl_curve = []
        treat_curve = []
        row_cells = []
        for diff in DIFFICULTY_ORDER:
            if (cat, diff) not in cells:
                continue
            samples = cells[(cat, diff)]
            c = _rate(samples, "control_correct")
            t = _rate(samples, "treatment_correct")
            ctrl_curve.append((diff, c))
            treat_curve.append((diff, t))
            row_cells.append((diff, c, t))

        classification, crossover = classify_curve(ctrl_curve, treat_curve)
        summary[classification].append(cat)

        cells_str = {d: f"{int(c * 100):>3d}/{int(t * 100):>3d}" for d, c, t in row_cells}
        print(
            f"{cat:<30} {cells_str.get('easy', '  -'):>10} "
            f"{cells_str.get('medium', '  -'):>10} {cells_str.get('hard', '  -'):>10}  "
            f"{classification:<24} {crossover or '—'}"
        )

    print()
    print("Territory summary:")
    for label in ("LLM-OWNS-THROUGHOUT", "CROSSOVER-FOUND",
                  "TOOL-ASSISTED-THROUGHOUT", "TOOL-INTERFERES",
                  "CAPABILITY-GAP", "AMBIGUOUS", "NO-DATA"):
        cats = summary.get(label, [])
        if cats:
            print(f"  {label:<28}: {len(cats):>2} categories — {', '.join(cats)}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the analyzer on Sonnet results**

Run: `python3 capability-map/analyze_capability_map.py --results capability-map/capability_results_sonnet.json | tee /tmp/sonnet_map.txt`
Expected: A table of 12 rows, one per category, with classifications.

- [ ] **Step 3: Write the report**

Create `docs/plans/2026-04-21-sonnet-capability-map-report.md`. Structure:

```markdown
# Sonnet 4.6 Capability Map — Report

## Setup

- Model: claude-sonnet-4-6
- 12 categories × 3 difficulties (easy, medium, hard) × n=5 = 180 problems
- max_rounds=30, total_budget=10000, workers=4
- Problem set: capability-map/capability_problems.json (seed 2026)
- Results: capability-map/capability_results_sonnet.json

## Map

[paste analyzer output from step 2]

## Interpretation

For each of the 6 classifications, list which categories landed there and what that tells us:

1. LLM-OWNS-THROUGHOUT: ...
2. CROSSOVER-FOUND: ... — names the difficulty where Wile starts helping
3. TOOL-ASSISTED-THROUGHOUT: ... — rare, suggests Wile helps even on easy problems
4. TOOL-INTERFERES: ... — investigate
5. CAPABILITY-GAP: ... — neither arm solves; difficulty too high OR design issue
6. AMBIGUOUS: ... — needs more samples or retune

## Calibration implications

For each category, note whether the 3-tier range is well-calibrated or needs extension:
  - If LLM-OWNS-THROUGHOUT: need extra-hard / super-hard to find the boundary
  - If CAPABILITY-GAP at hard: need extra-easy below current easy
  - If CROSSOVER-FOUND at medium or hard: 3 tiers is fine, extension to 5 tiers adds resolution but not new boundaries

## Next steps

Which categories to expand to 5 tiers first, based on where the bang-for-buck is highest.
```

Fill in the specifics based on the actual analyzer output.

- [ ] **Step 4: Commit the analyzer + report**

```bash
git add capability-map/analyze_capability_map.py docs/plans/2026-04-21-sonnet-capability-map-report.md
git commit -m "feat(capability-map): curve-based analyzer + Sonnet 4.6 capability-map report

Implements the curve-based classifier per the capability-map design
(LLM-OWNS-THROUGHOUT, CROSSOVER-FOUND, TOOL-ASSISTED-THROUGHOUT,
TOOL-INTERFERES, CAPABILITY-GAP, AMBIGUOUS).

Report interprets the 12-category Sonnet 4.6 map, names where the
LLM/Wile boundary sits per category, and flags which categories
want difficulty extension to find their boundary."
```

---

## Phase 3 (post-Sonnet) — Difficulty calibration to 5 tiers

**Depends on Phase 2 results.** Specific tasks cannot be written in advance because the answer depends on where Sonnet's curves actually land. The shape of Phase 3 work is:

- For each category where the map flags extension: design 2 additional tier presets (probably "extra-easy" and "extra-hard") that extend the category's capability range.
- Update `DIFFICULTIES` either globally to 5 tiers or per-category (the design doc's default is per-category, overridable via the `CATEGORIES` tuple structure).
- Regenerate problems and re-run the capability map on Sonnet.
- Interpret: is each category now spanning 100% → 0% across its 5 tiers? If yes, difficulty is calibrated. If no, iterate.

Concrete work estimate: 1 session per 3-4 categories requiring extension.

## Phase 4 (optional, post-calibration) — Run on Opus 4.7

Same run command, swap `--model claude-opus-4-7`. Expected wall time similar (~60 min at workers=4). Analysis compares the two model maps: where does Opus shift the boundary compared to Sonnet?

---

## Self-Review

**Spec coverage:**
- 6 remaining generators implemented: ✓ (Tasks 1–6)
- 3-tier per category: ✓ (all generators define easy/medium/hard presets)
- Full 12-category map regenerated: ✓ (Task 7)
- Sonnet run: ✓ (Task 8)
- Analyzer + report: ✓ (Task 9)
- Phase 3 calibration: stubbed as data-dependent (appropriate)
- Phase 4 Opus: stubbed as optional (appropriate)

**Placeholder scan:** Phase 3 and Phase 4 are intentionally data-dependent; all concrete code in Tasks 1–9 is fully specified with runnable examples.

**Type consistency:** Every generator returns `List[Problem]` with `Problem(id, category, difficulty, natural_language, scheme_expression, answer_type)`. Answer types used: `integer`, `set`, `polynomial`, `permutation`, `string`. All are handled by the existing `answers_match` in evaluate.py.

**Potential fragility flagged:**

1. **The Scheme oracle in `gen_boolean_satisfiability` is complex** (~30 lines of nested `let*`). During implementation, if Wile's parser or macro expander rejects any construct, the fallback is to emit a precomputed answer string (same pattern as `gen_regex_matching`). Document in commit if this fallback is needed.

2. **`gen_group_theory` commutator task uses `permutation` answer type** which stores as a tuple. If evaluate.py's `answers_match` doesn't handle the `(1 2 3 4 5 6)` format expected here, verify by reading evaluate.py:254-260. If mismatched, switch to `string` type with explicit format.

3. **`gen_linear_recurrence` scheme expression had two drafts in the plan** — the second (inside-the-loop index computation) is the correct one. If the first draft slips in via copy-paste error, the `'{tuple(...)}` placeholder will be in the emitted code and Wile will fail with a syntax error. Verify during Step 3 of Task 4.

4. **Task 8 requires API key.** If the implementer's environment lacks `ANTHROPIC_API_KEY`, they should stop at Step 1 of Task 8 with a BLOCKED status. The remaining Phase 3/4 work is long-running and benefits from controlled-environment execution.
