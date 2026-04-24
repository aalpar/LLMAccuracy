# LLM / Wile Capability Map — Design

## Research question

**Across a broad set of mathematical-reasoning problem categories, which territories does the LLM solve alone, which territories does LLM + Wile solve that the LLM cannot, and which territories are out of reach for both?**

The existing `algebra-accuracy` benchmark measures per-cell A/B deltas at calibrated difficulty. This project answers a different question: it classifies *territories* rather than measuring them. The goal is a map, not a ruler.

## Scope and constraints

**In scope:**

- Mathematical reasoning categories where correctness has a deterministic ground-truth answer
- A/B regime: LLM alone (control) vs LLM + Wile MCP (treatment). No other tool regimes in this project.
- Shallow sampling per category (n=5) — classification, not significance testing

**Out of scope:**

- Go code analysis / wile-goast (separate project if/when this map succeeds)
- Fine-grained difficulty sweeps within a category (that's what algebra-accuracy does)
- Statistical significance at any cell (n=5 is deliberately too small for that)

**Hard constraint:** Wile is the only tool the LLM has access to. Ground-truth answers must also come from Wile, with one exception: the three categories Wile is actively adding (`linear_recurrence`, `boolean_satisfiability`, `group_theory`) are stubbed in this design and generators will be implemented when the Wile primitives land.

## Taxonomy — 12 categories (9 active, 3 stubbed)

Each category specifies: description, sample problem, answer type, Wile readiness, generator source.

### 1. `modular_arithmetic` — Wile-ready

- **Description:** Ring operations (add, multiply, negate) in Z/nZ for prime n.
- **Sample:** `((a + b) × c) mod p`, where a, b, c are small integers and p is a large prime.
- **Answer type:** `integer` (non-negative, < p)
- **Wile primitives:** `ring-plus`, `ring-times`, `modular-ring`
- **Generator source:** existing `gen_modular` in `algebra-accuracy/generate.py`

### 2. `tropical_semiring` — Wile-ready

- **Description:** Tropical semiring operations (⊕ = min, ⊗ = +) on a balanced expression tree.
- **Sample:** Balanced tree of `min` and `+` operators over small integers.
- **Answer type:** `integer`
- **Wile primitives:** `tropical-semiring`, `semiring-plus`, `semiring-times`
- **Generator source:** existing `gen_tropical`

### 3. `powerset_lattice` — Wile-ready

- **Description:** Lattice operations (join = ∪, meet = ∩) on subsets of a finite universe.
- **Sample:** Nested `∪`/`∩` expression over subsets of `{a..p}`.
- **Answer type:** `set`
- **Wile primitives:** `powerset-lattice`, `lattice-join`, `lattice-meet`
- **Generator source:** existing `gen_powerset_lattice`

### 4. `monoid_fold` — Wile-ready

- **Description:** Fold a sequence using a monoid's binary operation. Tests whether LLM can identify *which* operation a named monoid performs (e.g., "tropical additive monoid" = min, not +).
- **Sample:** "Compute the product mod p of the tropical-additive folds (min) of these N sequences."
- **Answer type:** `integer`
- **Wile primitives:** `monoid-fold`, `semiring->additive-monoid`, `modular-ring`
- **Generator source:** existing `gen_monoid_fold`

### 5. `set_closure` — Wile-ready, new generator

- **Description:** Compute the transitive closure of a set under a given operation (e.g., closure of `{3, 5}` under addition mod 11).
- **Sample:** "Find the closure of `{3, 5}` under addition in Z/11Z. Return the resulting set in `{...}` notation."
- **Answer type:** `set` of integers
- **Wile primitives:** `closure-close` (per 2026-04-16 memory note)
- **Generator source:** NEW — `gen_set_closure`. Small generator using `closure-close` as oracle.

### 6. `graph_reachability` — Wile-ready, new generator

- **Description:** On a directed graph, is vertex `v` reachable from vertex `u`? Alternatively: what is the set of vertices reachable from `u`?
- **Sample:** "On the directed graph with edges `{(a,b), (b,c), (c,a), (d,e)}`, give the set of vertices reachable from `a`."
- **Answer type:** `set` of vertex names
- **Wile primitives:** `fixpoint` + adjacency-list representation. Reachability is a fixed-point computation on set extension.
- **Generator source:** NEW — `gen_graph_reachability`.

### 7. `prime_factorization` — Wile-ready, new generator

- **Description:** Given `n`, return its prime factorization.
- **Sample:** "Factor 360. Give the factorization as a sorted list of primes with multiplicities, e.g., `(2 2 2 3 3 5)`."
- **Answer type:** `polynomial` (reusing the sorted-integer-list type)
- **Wile primitives:** Confirm at implementation time whether Wile has a built-in factorization. If not, write a 10-line trial-division routine in the generator's scheme-script section — good enough for n < 10^6. The LLM treatment arm sees the same Wile regardless (no new primitive shipped to production Wile for this).
- **Generator source:** NEW — `gen_prime_factorization`. Pick n in a range where factoring is tractable (say < 10^6).

### 8. `combinatorial_counting` — Wile-ready, new generator

- **Description:** Count discrete structures. Expected LLM-owned territory (LLM knows combinatorial formulas), but worth probing.
- **Sample:** "How many ways can you arrange 7 people in a row such that person A sits next to person B? Give a non-negative integer."
- **Answer type:** `integer`
- **Wile primitives:** Factorial, binomial — standard arithmetic. No special library needed.
- **Generator source:** NEW — `gen_combinatorial_counting`. Template-based: factorial, permutations with constraints, binomial coefficients, small Catalan / Stirling numbers.

### 9. `regex_matching` — Wile-ready, new generator

- **Description:** Does regex `r` match string `s`? Or: how many matches does `r` have in `s`? Expected LLM-owned; worth confirming.
- **Sample:** "Does the regex `a(b|c)*d` match `abbccd`? Answer `yes` or `no`."
- **Answer type:** `string` — the LLM writes `yes` or `no` literally and the existing string-fallback path in `answers_match` handles comparison. Avoids adding a new `boolean` type.
- **Wile primitives:** Scheme's built-in regex support via `regex-match` (verify availability) or SRFI-115.
- **Generator source:** NEW — `gen_regex_matching`. Hand-picked regex/string pairs of varying complexity.

### 10. `linear_recurrence` — **STUBBED, Wile-incoming**

- **Description:** Solve `a_n = c_1 * a_{n-1} + ... + c_k * a_{n-k}` with initial conditions, return `a_n` for given `n`. Fibonacci-like.
- **Sample:** "Let a_0 = 1, a_1 = 2, a_n = 3*a_{n-1} - 2*a_{n-2}. What is a_30?"
- **Answer type:** `integer`
- **Wile primitives:** Matrix exponentiation, characteristic polynomial. **Wile does not currently support these.** (Per 2026-04-16 memory: "Wile algebra does NOT currently support this — needs matrix operations, characteristic polynomial computation, closed-form solving.")
- **Generator source:** STUB — `gen_linear_recurrence` with a comment explaining it requires Wile matrix support. Implement when Wile ships it.

### 11. `boolean_satisfiability` — **STUBBED, Wile-incoming**

- **Description:** Small-k SAT: is a given CNF formula satisfiable? If yes, return a satisfying assignment.
- **Sample:** "Is `(x1 ∨ ¬x2) ∧ (¬x1 ∨ x3) ∧ (x2 ∨ ¬x3)` satisfiable? If yes, give an assignment as `(x1=T x2=T x3=T)`."
- **Answer type:** string (e.g., `"UNSAT"` or `"(x1=T x2=F x3=T)"`). Needs new answer-matching logic.
- **Wile primitives:** SAT solver. Not currently in Wile.
- **Generator source:** STUB — `gen_boolean_satisfiability`. Implement when Wile ships SAT.

### 12. `group_theory` — **STUBBED, Wile-incoming (maybe)**

- **Description:** Basic group operations on permutation groups: compose permutations, compute order of an element, check if an element is the identity.
- **Sample:** "In S_5, what is the order of the permutation (1 2 3 4 5) → (2 3 1 5 4)? Give a positive integer."
- **Answer type:** `integer` or `permutation`
- **Wile primitives:** Permutation composition, group order. Partial support may exist; confirm at implementation time.
- **Generator source:** STUB — `gen_group_theory`. Implement when Wile has confirmed support.

## Measurement design

### Sample size and difficulty sweep

**n = 5 per (category, difficulty) cell.** Per-cell accuracy has resolution to roughly 20-percentage-point buckets (0/5, 1/5, 2/5, 3/5, 4/5, 5/5). That's enough to detect curve shape and locate crossovers; it's *not* enough for statistical significance. A cell that looks ambiguous after n=5 gets bumped to n=15 in a follow-up pass.

**Three difficulty levels per category: easy, medium, hard.** Every category exposes the same three tiers so the map has a uniform difficulty axis. The capability map lives or dies on the curve shape, not on a single-point classification — a category is interesting because *of what changes as difficulty increases*, not because it lands in one bucket at one difficulty.

Total problem count per full map run: 12 categories × 3 difficulties × 5 samples = 180 problems. Per-session pilots stay much smaller (e.g., 4 categories × 3 × 5 = 60 in Session 2).

### Per-category classification — curve-based

Each category produces a pair of curves: ctrl-accuracy vs difficulty, and treat-accuracy vs difficulty. The classifier reads the curves, not a single point:

| Classification | Curve shape | Meaning |
|---------------|-------------|---------|
| **LLM-OWNS-THROUGHOUT** | ctrl holds ≥ 70% across all 3 difficulties; treat matches or trails slightly | No crossover within tested range. LLM can handle this category at our hardest tier without help. |
| **CROSSOVER-FOUND** | ctrl drops below 50% at some difficulty, treat stays ≥ 20pp higher at that difficulty | The Wile-helps boundary. Names the specific difficulty where the regime changes. |
| **TOOL-ASSISTED-THROUGHOUT** | treat ≥ ctrl by 20pp at *every* difficulty (even easy) | Unusual — tools help even on trivially easy problems in this category. Investigate. |
| **CAPABILITY-GAP** | Both arms collapse to < 30% together by hard (or earlier) | Neither regime solves this at our hardest tier. Needs new tool primitives or easier problem shapes. |
| **TOOL-INTERFERES** | treat < ctrl by 20pp at every measured difficulty | Tools actively hurt. Investigate — usually means LLM is using the tool wrongly or the problem doesn't suit tool-based decomposition. |
| **AMBIGUOUS** | Fallthrough — curve doesn't match any clean pattern | Most common when n=5 is insufficient at some difficulty. Flag for n=15 re-run of specific cells. |

A single **boundary number** per category supplements the classification — the difficulty at which the crossover (if any) occurs. For `CROSSOVER-FOUND`, it's the highest difficulty where ctrl ≥ treat or where both are within 10pp; for others, the value is null.

### Analyzer output

Per category, report the curve shape plus classification:

```
Category                   easy      medium     hard   Classification          Crossover
─────────────────────────────────────────────────────────────────────────────────────────
modular_arithmetic       100/100   100/100   80/100   CROSSOVER-FOUND (assist)   hard
tropical_semiring        100/100    80/100   60/ 40   TOOL-INTERFERES            —
powerset_lattice         100/100    80/ 80   20/ 60   CROSSOVER-FOUND (essential)  medium-hard
combinatorial_counting   100/100   100/100  100/100   LLM-OWNS-THROUGHOUT        —
graph_reachability        60/100    40/100   20/ 80   TOOL-ASSISTED-THROUGHOUT   easy
linear_recurrence           —         —        —      STUBBED (Wile pending)     —
...

Territory summary:
  LLM-OWNS-THROUGHOUT          : 2 categories — combinatorial_counting, regex_matching
  CROSSOVER-FOUND              : 3 categories — modular_arithmetic (hard), powerset_lattice (medium-hard), ...
  TOOL-ASSISTED-THROUGHOUT     : 1 category   — graph_reachability
  TOOL-INTERFERES              : 1 category   — tropical_semiring
  CAPABILITY-GAP               : 0
  AMBIGUOUS                    : 2 categories — (need n=15 at specific cells)
  STUBBED                      : 3 categories — linear_recurrence, boolean_satisfiability, group_theory
```

Each row shows control-accuracy/treatment-accuracy at each difficulty (`60/100` = 60% ctrl, 100% treat). The `Crossover` column names the difficulty bucket where the regime change was detected. This table, *not* a single-label classification, IS the capability map.

## Architecture

### New directory: `capability-map/`

The capability map is a separate probe from `algebra-accuracy/`. Sibling directory keeps the two projects' concerns clean.

```
capability-map/
  generate_capability_problems.py   # taxonomy + per-category generators (some import from algebra-accuracy)
  analyze_capability_map.py         # classifier + territory report
  capability_problems.json          # generator output
  capability_results.json           # evaluate.py output
```

### Harness reuse

`evaluate.py` from `algebra-accuracy/` is reused unchanged. The capability-map generator produces a problems file in the same JSON schema (`id`, `category`, `difficulty`, `natural_language`, `scheme_expression`, `answer`, `answer_type`). The existing `evaluate.py --problems ... --output ...` command runs it as-is.

Per-category generators within `generate_capability_problems.py` import functions from `algebra-accuracy/generate.py` where possible:

- `from generate import gen_modular, gen_tropical, gen_powerset_lattice, gen_monoid_fold`

New generators (categories 5–12) are defined locally in `generate_capability_problems.py`. This keeps the algebra-accuracy generator focused on algebra; capability-map-specific generators stay in the capability-map project.

### Difficulty sweep per category

The capability map uses a three-tier difficulty sweep (easy, medium, hard) per category — the same three tiers for every category so the map has a uniform x-axis. For reused generators (`gen_modular`, `gen_tropical`, `gen_powerset_lattice`, `gen_monoid_fold`), these tiers already exist as `difficulty` parameters. For new generators (Sessions 3-4), each must define its own easy/medium/hard presets as part of its implementation.

The shared `DIFFICULTIES` constant at the top of `generate_capability_problems.py` encodes this as a contract: any new category that doesn't expose three tiers fails the design review.

If the pilot shows that some categories' "hard" is still LLM-owned (both curves near 100% at hard), we extend *those specific categories* to include "extra-hard" in a follow-up. The default three-tier sweep is the starting line, not a ceiling.

## Incremental delivery plan

### Session 1 (this session) — design

- Write + commit this design doc. Review and approve with the user.

### Session 2 — scaffolding + reused categories

- Create `capability-map/` directory structure
- Implement `generate_capability_problems.py` skeleton with dispatch to per-category generators
- Wire up the 4 reused generators (modular_arithmetic, tropical_semiring, powerset_lattice, monoid_fold)
- Verify `evaluate.py` runs cleanly on a 4×n=5 = 20-problem pilot
- Commit a partial map (4 cells) as an early-signal deliverable

### Session 3 — new Wile-ready generators

- Implement `gen_set_closure`, `gen_graph_reachability`
- Confirm `closure-close` / `fixpoint` are available in Wile and produce ground truth
- Add to capability problem set; re-run

### Session 4 — remaining Wile-ready generators

- Implement `gen_prime_factorization`, `gen_combinatorial_counting`, `gen_regex_matching`
- Verify answer_type mechanics for regex (add `boolean` if needed, or coerce to integer)
- Full 7-category map runnable

### Session 5 — analyzer + report

- Implement `analyze_capability_map.py` with the 6-class classifier
- Produce the first territory map
- Interpret: which categories fell where? Surprises?
- Commit a capability-map report to `docs/plans/`

### Session 6+ — stubbed categories (as Wile primitives land)

- When Wile ships `linear_recurrence` support, fill in `gen_linear_recurrence`
- Similarly for `boolean_satisfiability` and `group_theory`
- Re-run map, update report

## Open questions (not blocking design approval)

1. ~~**Answer type for regex:**~~ Resolved inline: use string `yes`/`no`.

2. **Difficulty parameter for reused generators:** each of `gen_modular` / `gen_tropical` / etc. takes a difficulty param that maps to a preset tuple. For the capability map, we use `"medium"` on all. If any reused category comes out trivially 100%-100% at "medium", drop to the existing "hard" difficulty in a follow-up pass. Not a design concern; a tuning concern.

3. **When does the first classifier tune happen?** After Session 5's first run. The thresholds (80%, 30%, 70%, 0.20 delta) are guesses. Real data may suggest shifting them. Keep them in one place (constants at the top of `analyze_capability_map.py`) so tuning is one-commit.

## Success criteria

This design is successful if it produces a capability map that:

- Classifies each of the 7 currently-implementable cells into a named category with defensible thresholds
- Reveals at least one surprise — a category that landed differently than expected (LLM-owned where you'd expect Wile-essential, or vice versa)
- Provides a concrete list of *the next categories worth probing* — cells where the classification is ambiguous and more samples would resolve
- Is trivially extensible when Wile lands the deferred primitives
