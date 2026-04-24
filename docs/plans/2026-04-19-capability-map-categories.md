# Capability Map — Category Content Design

This document expands the `Taxonomy` section of `2026-04-19-capability-map-design.md` with deep per-category analysis. The capability map's informational value depends on **what each category tests**, not just the A/B measurements. This document answers, for each of the 12 categories:

1. **What cognitive capability does it probe?** — the thing we are testing the LLM on.
2. **Why is it a useful probe?** — what it distinguishes from other categories.
3. **What structural property defines correct answers?** — what the LLM has to *not* lose track of.
4. **Where is the expected LLM/Wile boundary?** — predicted crossover location.
5. **How do easy/medium/hard differ?** — what varies across tiers.
6. **Example problem per tier** — to anchor the design.

The per-category analyses are grouped by **cognitive demand** at the end: execution-heavy, structure-recognition, search, iteration-to-convergence. A good capability map should span these demands, not just the subject-matter domains.

---

## 1. `modular_arithmetic` — Wile-ready

**Tests:** Arithmetic chains in a finite ring Z/nZ. The LLM must track modular reduction through a sequence of additions and multiplications without losing precision.

**Why valuable:** Classical demonstration of LLM arithmetic error. A single arithmetic mistake early in the chain propagates to the final answer. Wile's `modular-ring` is immune to this.

**Structural invariant:** Ring axioms. `ring-plus` is associative, commutative, has identity 0; `ring-times` distributes over it. Reduction mod n happens *at every step*, not just at the end — the LLM must know that e.g. `(a + b) × c mod n = ((a mod n + b mod n) × c mod n) mod n`, and that holding off on reduction is wrong because intermediate products overflow.

**Expected LLM/Wile boundary:** Sonnet 4.6 calibration placed this around 5-digit moduli. Opus 4.7's beta run (n=30) shows 100% control at "hard" (4-digit moduli, 12-value chains). Real LLM boundary is probably `super-hard` (100k-scale moduli, 16-value chains) or `ultra-hard` (7-digit).

**Tier semantics:** Difficulty grows along two dimensions — *modulus size* (bits to track) and *chain length* (steps to execute without error).

| Tier | Modulus | Chain length | Expected LLM | Expected Wile |
|------|---------|-------------|--------------|---------------|
| easy | 3-digit primes (~1000) | 8 values | 100% | 100% |
| medium | 4-digit primes (~5000) | 10 values | 100% | 100% |
| hard | 4-digit primes (~10^4) | 12 values | 100% | 100% |
| extra-hard | 5-digit primes (~5×10^4) | 14 values | ~80% | 100% |
| super-hard | 6-digit primes (~10^5) | 16 values | 40-60% | 100% |
| ultra-hard | 7-digit primes (~10^6) | 20 values | 0-20% | 100% |

**Example (hard tier):** "What is `((((3117 × 4616 + 4692) × 1340) − 2329) × 3945) mod 4999`? Give a non-negative integer."

---

## 2. `tropical_semiring` — Wile-ready

**Tests:** Does the LLM understand that **structure-theoretic names override familiar arithmetic names**? In the tropical semiring, ⊕ = min and ⊗ = +. "Semiring-plus" does not mean `+`. "Semiring-times" does not mean `×`. This is the cleanest test in the taxonomy of whether the LLM reasons about *structure* or merely *name-matches*.

**Why valuable:** A direct probe of symbolic vs. structural thinking. If the LLM reads "additive monoid of the tropical semiring" and types `+` into its reasoning, it has failed the probe — regardless of how well it can compute.

**Structural invariant:** Semiring axioms under unusual interpretation. ⊕ is idempotent (min(a,a)=a) and has identity +∞, not 0. ⊗ has identity 0, not 1. The LLM must hold these renamings consistently through nested operations.

**Expected LLM/Wile boundary:** The "understands the renaming" question is binary per-problem — either the LLM identifies the operation correctly or not. So this category's failure pattern is different from modular: errors should cluster at problem *types* (new operations) rather than along a length axis. Opus 4.7 at hard shows 80-100% control — the LLM appears to understand tropical renaming. Boundary likely at extra-hard where tree depth forces more careful tracking, not because the concept is harder but because execution length is.

**Tier semantics:** Difficulty grows along *tree depth* and *tree breadth*.

| Tier | Tree size | Expected LLM | Expected Wile |
|------|-----------|--------------|---------------|
| easy | depth 2, ~4 values | 100% | 100% |
| medium | depth 3, ~10 values | 100% | 100% |
| hard | depth 4, ~15 values | 80-100% | 100% |
| extra-hard | depth 5, ~25 values | 40-60% | 100% |

**Example (medium tier):** "In the tropical semiring, ⊕ = min, ⊗ = +. Compute `(3 ⊗ 7) ⊕ (4 ⊕ 2) ⊗ 8` step-by-step. Give an integer."

Watch for: does the LLM emit `3+7=10`, `min(4,2)=2`, `min(10, 2+8)=10`? Or does it slip into `3+7 + min(4,2) × 8`?

---

## 3. `powerset_lattice` — Wile-ready

**Tests:** Precise execution of nested set operations over a finite universe. Not the concept — the concept is simple — but **careful tracking of set membership through many compositions**.

**Why valuable:** Distinguishes "knows what ∪ and ∩ mean" (trivial) from "can track 16 elements through 25 nested operations without losing one" (non-trivial). The failure mode is bookkeeping, not comprehension.

**Structural invariant:** Lattice axioms over the powerset. ∪ and ∩ are idempotent, commutative, associative, and mutually absorptive. The answer is always a subset of the universe; extraneous elements or missing elements are both failures.

**Expected LLM/Wile boundary:** The beta run (n=30) showed this exactly: ctrl=93% at medium, 33% at hard. Control boundary is between medium and hard. Treatment at hard shows +23% lift (57%) when round-cap removed — tools help, but this category still has residual difficulty even with Wile (because Wile must be asked correctly).

**Tier semantics:** Difficulty grows along *universe size* and *expression depth*.

| Tier | Universe | Expression ops | Expected LLM | Expected Wile |
|------|----------|----------------|--------------|---------------|
| easy | 8 elements | 6-10 ops | 100% | 100% |
| medium | 12 elements | 12-16 ops | 80-100% | 90-100% |
| hard | 16 elements | 20-30 ops | 30-40% | 55-65% |
| extra-hard | 20 elements | 35-50 ops | 0-10% | 30-40% |

**Example (medium tier):** "In the power set lattice on {a, b, c, d, e, f, g, h}, compute `(({a, c, f} ∪ {b, d}) ∩ {c, d, e, f}) ∪ ({b, g} ∩ {a, b, c})`. Give the answer in `{...}` notation."

---

## 4. `monoid_fold` — Wile-ready

**Tests:** A pure variant of `tropical_semiring` — strips away the expression tree and asks directly: **can the LLM identify which operation a named monoid performs**? Then correctly fold a list using that operation.

**Why valuable:** Isolates the structure-recognition question from execution depth. If the LLM fails this, it fails because of a conceptual error (wrong operation), not because of a bookkeeping error. Very clean diagnostic.

**Structural invariant:** Four possible monoid operations depending on (ring/semiring) × (additive/multiplicative) slot:
- tropical additive monoid: min
- tropical multiplicative monoid: +
- modular additive monoid: + mod n
- modular multiplicative monoid: × mod n

The LLM's job is to recognize which slot the problem specifies and apply the right operation to all sequence elements, then combine across sequences.

**Expected LLM/Wile boundary:** Per beta (n=30 at `medium`): both arms at 100%. The concept is well-understood by Opus 4.7. Difficulty ceiling comes from *execution length* (many sequences × long sequences → output-bound). The pilot's `hard` tier (50 seqs × length 80) was output-bound for both arms — not a capability test.

**Redesign note:** The current `hard` tier tests output capacity, not capability. For the capability map, `hard` should test concept-application under *moderate* execution length. Proposed redesign:

| Tier | Sequences × length | Expected LLM | Expected Wile |
|------|---------------------|--------------|---------------|
| easy | 8 × 15 | 100% | 100% |
| medium | 15 × 25 | 90-100% | 100% |
| hard | 25 × 40 | 50-70% | 100% |
| extra-hard | 40 × 60 | 10-30% | 100% |

The original "hard" tier (50×80) moves to an untested range beyond extra-hard; it's not informative for capability-mapping.

**Example (medium tier):** "Compute the product mod 99991 of the tropical-additive monoid folds (min) of these sequences: [...15 lists of length 25...]."

---

## 5. `set_closure` — Wile-ready, new generator needed

**Tests:** **Fixed-point computation.** Given a starting set S and a unary operator f on sets (typically generated by some operation), compute the smallest superset of S that is closed under f.

**Why valuable:** Tests iteration-to-convergence. The LLM must recognize that the answer is the limit of `S ⊆ S∪f(S) ⊆ S∪f(S∪f(S)) ⊆ ...` and that the iteration must run *until no new elements are added*, not for a fixed number of steps. This is where LLMs often stop too early: they iterate 3-4 times, see "it looks converged," and report.

**Structural invariant:** The closure is unique and is the least fixed point of the operator. It is a superset of S. It is closed under f (every f(x) with x in closure is in closure).

**Expected LLM/Wile boundary:** LLM at easy (closure size 5-10, few iterations): should be fine. At medium (size 15-30, 5-10 iterations): error-prone. At hard (size 50+, 10+ iterations with multiple operators): likely fails. Wile's `fixpoint` primitive makes this mechanical.

**Tier semantics:** Difficulty grows along *starting set size*, *closure size*, and *number of generating operations*.

| Tier | Setup | Expected LLM | Expected Wile |
|------|-------|--------------|---------------|
| easy | \|S\|=2, single op (a+b mod 11), closure ~7 | 80-100% | 100% |
| medium | \|S\|=3, two ops (a+b mod 13, 2a mod 13), closure ~12 | 40-60% | 100% |
| hard | \|S\|=3, three ops in Z/17Z, closure ~17 (whole ring) | 10-30% | 100% |

**Example (easy tier):** "Find the closure of `{3, 5}` under the operation `(a, b) → (a + b) mod 11`. Give the result as a sorted list of integers in `(...)` notation."

**Wile primitive verification needed:** Memory says `closure-close` exists in `(wile algebra)`. Probe during implementation.

---

## 6. `graph_reachability` — Wile-ready, new generator needed

**Tests:** Transitive closure on a directed graph. Given vertex set, edge list, and source vertex `u`, return the set of vertices reachable from `u`.

**Why valuable:** Direct test of mechanical graph traversal. LLMs pattern-match on *small* graphs well — you can see a 5-vertex graph in one mental view. The interesting failure is at 15+ vertices where visual reasoning breaks down and algorithmic execution is required.

**Structural invariant:** Reach(u) is the least set R such that `u ∈ R` and `∀ (v,w) ∈ edges: v ∈ R ⇒ w ∈ R`. Unique; computable via BFS, DFS, or fixed-point iteration on the adjacency relation.

**Expected LLM/Wile boundary:** LLM is strong at small graphs; fails at dense + cyclic larger graphs. Wile's `fixpoint` over adjacency handles any size mechanically.

**Tier semantics:** Difficulty grows along *vertex count*, *edge density*, and *cycle complexity*.

| Tier | Graph | Expected LLM | Expected Wile |
|------|-------|--------------|---------------|
| easy | 5 vertices, 6 edges, 1 cycle | 100% | 100% |
| medium | 10 vertices, 15 edges, 2-3 cycles | 60-80% | 100% |
| hard | 20 vertices, 40 edges, multiple interleaved cycles | 20-40% | 100% |

**Example (easy tier):** "Given the directed graph with vertices `{a, b, c, d, e}` and edges `{(a,b), (b,c), (c,a), (d,e), (a,e)}`, give the set of vertices reachable from `a`. Return as a sorted set in `{...}` notation."

---

## 7. `prime_factorization` — Wile-ready, new generator needed

**Tests:** Factor a positive integer `n` into primes with multiplicities. Return the sorted factorization.

**Why valuable:** Classical "LLM can't do big arithmetic" probe. But also tests whether the LLM knows small-prime shortcuts (2, 3, 5, 7 divisibility rules) and applies them systematically, or whether it blunders into trial-and-error.

**Structural invariant:** Unique factorization theorem — for any n ≥ 2, there is a unique sorted list of primes `(p_1, p_2, ..., p_k)` with p_1 ≤ p_2 ≤ ... such that `n = p_1 × p_2 × ... × p_k`. Order of output matters for grading; answer is sorted ascending with multiplicities listed individually.

**Expected LLM/Wile boundary:** LLM handles small n (< 1000) by inspection; medium (10^4-10^5) requires real factoring and the LLM will skip primes; hard (10^6+) is out of reach without tool. The interesting case: semiprime `n = p × q` with p, q both ~1000 — hardest for LLM, trivial for Wile.

**Tier semantics:** Difficulty grows along *n magnitude* and *presence of large primes*.

| Tier | n range | Structure | Expected LLM | Expected Wile |
|------|---------|-----------|--------------|---------------|
| easy | 100 - 1000 | often with small factors | 80-100% | 100% |
| medium | 10^4 - 10^5 | mixed small and medium primes | 40-60% | 100% |
| hard | 10^6 - 10^7 | includes semiprimes with 4-digit primes | 10-20% | 100% |

**Example (easy tier):** "Factor 360. Give the answer as a sorted list of primes with multiplicities, e.g., `(2 2 2 3 3 5)`."

**Wile primitive verification needed:** Wile has standard arithmetic (`gcd`, `modulo`). If no built-in factor, add trial-division via `integer-sqrt` + iteration inside the scheme expression. ~10 lines.

---

## 8. `combinatorial_counting` — Wile-ready, new generator needed

**Tests:** Count discrete structures under constraints. Tests whether the LLM **knows formulas** AND **applies them correctly under constraint composition**.

**Why valuable:** LLMs have combinatorial formulas memorized (n!, C(n,k), Stirling, Catalan). The probe is whether it applies the right formula to a disguised word problem and handles constraint interactions correctly. Unlike modular arithmetic, failure here is usually *analytic* (wrong formula) not *computational* (arithmetic slip).

**Structural invariant:** Exact integer answer via a counting formula. No ambiguity.

**Expected LLM/Wile boundary:** Opus 4.7 is probably strong at easy and medium. Wile doesn't add much here — the LLM already knows the formulas; Wile just verifies arithmetic. This category may land as `LLM-OWNS-THROUGHOUT`, which is *informative* — "combinatorial counting is LLM territory" is a real finding.

**Tier semantics:** Difficulty grows along *number of constraints* and *inclusion-exclusion depth*.

| Tier | Problem type | Expected LLM | Expected Wile |
|------|--------------|--------------|---------------|
| easy | straight permutation/combination, small n | 100% | 100% |
| medium | single constraint (adjacency, order), derangement | 60-90% | 100% |
| hard | multi-set inclusion-exclusion, 4+ constraints | 20-50% | 100% |

**Example (easy tier):** "How many ways can 7 distinct books be arranged in a row on a shelf? Give a positive integer."

**Example (hard tier):** "How many permutations of the letters `A A B B C C D` have no two adjacent letters equal? Give a positive integer."

---

## 9. `regex_matching` — Wile-ready (pending primitive verification), new generator needed

**Tests:** Does a regex pattern `r` match a string `s`? Binary yes/no answer.

**Why valuable:** Tests finite-automaton reasoning. LLMs know regex syntax but misjudge complex patterns — especially with overlapping character classes, anchors, and backreferences. Very discrete answer (yes or no), minimal grading ambiguity.

**Structural invariant:** Regex languages are exactly the regular languages. Match is well-defined by the automaton equivalent.

**Expected LLM/Wile boundary:** LLMs handle basic patterns (`a+b*c`) easily; fail on backreferences and lookaround. Wile with regex handles all uniformly.

**Tier semantics:** Difficulty grows along *regex feature complexity*.

| Tier | Pattern class | Expected LLM | Expected Wile |
|------|---------------|--------------|---------------|
| easy | literal, alternation, * / + | 100% | 100% |
| medium | character classes, anchors, bounded repetition | 70-90% | 100% |
| hard | backreferences, nested alternation, lookaround | 30-50% | 100% |

**Example (easy tier):** "Does the regex `a(b\|c)*d` match the string `abbccd`? Answer `yes` or `no`."

**Wile primitive verification needed:** Unclear whether Wile has SRFI-115 or another regex library. If not, this category either requires a Wile primitive addition or shifts to `STUBBED`.

---

## 10. `linear_recurrence` — STUBBED, Wile-incoming

**Tests:** Given a linear recurrence `a_n = c_1 a_{n-1} + c_2 a_{n-2} + ... + c_k a_{n-k}` with initial conditions `a_0, a_1, ..., a_{k-1}`, compute `a_N` for large `N`.

**Why valuable:** Tests whether LLM recognizes when naive iteration (O(N)) is infeasible and when matrix exponentiation (O(k^3 log N)) is the correct tool. For small N, direct iteration works; for N ≥ 30, arithmetic errors accumulate; for N ≥ 10^4, only the closed-form approach (via characteristic polynomial or matrix exp) works.

**Structural invariant:** Linear recurrences correspond to matrix-vector iteration: `[a_n, a_{n-1}, ...]ᵀ = M [a_{n-1}, a_{n-2}, ...]ᵀ` for a companion matrix M. a_N = (M^N v)_0 for initial vector v.

**Expected LLM/Wile boundary:** LLM handles Fibonacci F_10, F_20. Fails at F_50+. Wile with matrix exp handles F_10^6 instantly.

**Tier semantics:** Difficulty grows along *recurrence order* and *N magnitude*.

| Tier | Setup | Expected LLM | Expected Wile |
|------|-------|--------------|---------------|
| easy | order-2, N ≤ 20 | 80-100% | 100% |
| medium | order-2 or 3, N ≤ 50 | 30-60% | 100% |
| hard | order-3+, N ≥ 100 | 0-20% | 100% |

**Example (easy tier):** "Let a_0 = 1, a_1 = 1, a_n = a_{n-1} + a_{n-2}. Compute a_10. Give a positive integer."

**Stub status:** Implement when Wile has matrix exponentiation or characteristic-polynomial-based linear recurrence solving.

---

## 11. `boolean_satisfiability` — STUBBED, Wile-incoming

**Tests:** Given a CNF (Conjunctive Normal Form) formula, is it satisfiable? If yes, produce a satisfying variable assignment.

**Why valuable:** Tests systematic search. LLMs can reason about 3-4 variable SAT instances; beyond that, combinatorial explosion exceeds direct reasoning. The interesting LLM failure mode is **premature commitment** — LLM guesses an assignment and fails to backtrack when a conflict surfaces late.

**Structural invariant:** A 2-SAT instance is satisfiable iff no variable is in the same strongly connected component as its negation (in the implication graph). A k-SAT instance (k ≥ 3) is NP-complete; the standard approach is unit propagation + conflict-driven backtracking.

**Expected LLM/Wile boundary:** LLM handles 3 vars × 4 clauses trivially. Fails at 5 vars × 10 clauses. Wile with a SAT solver is instant.

**Tier semantics:** Difficulty grows along *variable count*, *clause count*, and *proximity to unsat*.

| Tier | Setup | Expected LLM | Expected Wile |
|------|-------|--------------|---------------|
| easy | 3 vars, 4 clauses, 2-SAT | 80-100% | 100% |
| medium | 5 vars, 8-12 clauses, 3-SAT | 30-60% | 100% |
| hard | 8 vars, 15-20 clauses, near-unsat | 10-30% | 100% |

**Example (easy tier):** "Is the CNF formula `(x_1 ∨ ¬x_2) ∧ (¬x_1 ∨ x_3) ∧ (x_2 ∨ ¬x_3)` satisfiable? If yes, give an assignment in the form `(x_1=T x_2=F x_3=T)`. If no, answer `UNSAT`."

**Stub status:** Implement when Wile ships a SAT solver.

---

## 12. `group_theory` — STUBBED, Wile-incoming (may be partially ready)

**Tests:** Permutation group computations — compose permutations, compute the order of an element, check commutativity, compute inverses and cycles.

**Why valuable:** Tests whether the LLM can apply group-theoretic reasoning under cycle decomposition. Formulas (Lagrange, cycle-length = order) are memorized; the test is application under non-trivial cycle structures.

**Structural invariant:** Group axioms (associativity, identity, inverses). Lagrange's theorem: element order divides group order. Cycle decomposition: order of an element = LCM of its cycle lengths.

**Expected LLM/Wile boundary:** S_3, S_4 trivial; S_5 and larger require systematic tracking that LLM will botch by hand. Wile with permutation-group library handles uniformly.

**Tier semantics:** Difficulty grows along *group size* and *cycle structure complexity*.

| Tier | Setup | Expected LLM | Expected Wile |
|------|-------|--------------|---------------|
| easy | S_3, S_4, single-cycle permutations | 80-100% | 100% |
| medium | S_5, multi-cycle permutations, order computation | 40-70% | 100% |
| hard | S_6+, commutator computations, conjugate classes | 10-30% | 100% |

**Example (easy tier):** "In S_5, what is the order of the permutation `(1 2 3 4 5) → (2 3 1 5 4)`? Give a positive integer."

**Stub status:** Verify whether Wile has permutation-group primitives. Memory says "partial." May be ready for easy tier only.

---

## Cross-cutting: cognitive demand

The 12 categories cluster along four cognitive demands. A well-designed capability map should span these clusters, not over-weight one.

| Cognitive demand | Categories | What it probes |
|------------------|-----------|----------------|
| **Execution precision** | `modular_arithmetic`, `powerset_lattice`, `monoid_fold`, `prime_factorization`, `linear_recurrence` | Track state precisely across many steps without slipping |
| **Structure recognition** | `tropical_semiring`, `monoid_fold`, `group_theory`, `regex_matching` | Identify the right operation/interpretation under non-obvious naming |
| **Search** | `boolean_satisfiability`, `combinatorial_counting` (constrained variants) | Enumerate possibilities, prune dead branches |
| **Iteration to convergence** | `set_closure`, `graph_reachability`, `linear_recurrence` (naive), `boolean_satisfiability` (DPLL) | Run until stable, not for N steps |

This grouping suggests useful predictions:
- LLM should be strong on **structure recognition** when concepts are standard (group theory) and weak when concepts are unusual (tropical semiring).
- LLM should fail on **iteration-to-convergence** at medium difficulty because it stops too early.
- LLM should be strong on **execution precision** for easy cases but degrade predictably as length increases.
- LLM should fail on **search** once the search space exceeds what it can enumerate in reasoning (probably ~20 possibilities).

If the empirical map contradicts these predictions, the predictions are wrong (useful). If it confirms them, we have structured evidence for a theory of LLM capability boundaries.

## Difficulty extension — a design decision

Several categories (`modular_arithmetic`, `tropical_semiring`, possibly `monoid_fold` after redesign) don't cross their LLM/Wile boundary within easy/medium/hard at current presets on Opus 4.7. Two ways to handle this:

1. **Extend those specific categories to 5-6 tiers.** `gen_modular` supports `extra-hard`, `super-hard`, `ultra-hard`. Use them.
2. **Leave the map ragged and flag "LLM-owns throughout tested range"** as a legitimate category-level finding.

For the *content* map, option 1 is better — it finds the boundary. For the *comparison* map across categories, ragged coverage is honest. **Recommendation: extend categories that obviously need it (modular_arithmetic, tropical_semiring); accept ragged coverage where the generator's difficulty range runs out.**

The shared `DIFFICULTIES = ["easy", "medium", "hard"]` constant should be retained as the default but overridable per category via an explicit second entry in `CATEGORIES`. E.g., `"modular_arithmetic": (["easy", "medium", "hard", "extra-hard", "super-hard"], gen_modular)`.

## What this document does NOT cover

- Generator implementation (Sessions 3–4).
- Analyzer classifier code (Session 5).
- Classifier threshold tuning — depends on real data, defer to post-pilot.
- Wile primitive verification per category — done at implementation time, not here.
