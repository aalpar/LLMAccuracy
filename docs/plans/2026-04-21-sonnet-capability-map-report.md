# Sonnet 4.6 Capability Map — Report

## Setup

- Model: `claude-sonnet-4-6`
- 12 categories × 3 difficulties (easy, medium, hard) × n=5 = **180 problems**
- Harness settings: `--max-rounds 30 --total-budget 10000 --workers 4 --condition both`
- Problem set: `capability-map/capability_problems.json` (seed 2026)
- Results: `capability-map/capability_results_sonnet.json`
- Wall time: ~38 min (parallel), serial-equivalent ~150 min
- Total accuracy: **74% control, 87% treatment, +13% delta**

## The Map

| Category                  | easy   | medium | hard   | Classification         | Where    |
|---------------------------|--------|--------|--------|------------------------|----------|
| `boolean_satisfiability`  | 60/100 |  0/ 60 |  0/ 20 | **CROSSOVER-FOUND**    | medium   |
| `combinatorial_counting`  |100/100 |100/100 | 80/ 80 | LLM-OWNS-THROUGHOUT    | —        |
| `graph_reachability`      |100/100 |100/100 |100/100 | LLM-OWNS-THROUGHOUT    | —        |
| `group_theory`            |100/100 |100/100 |100/100 | LLM-OWNS-THROUGHOUT    | —        |
| `linear_recurrence`       |100/100 | 80/100 |  0/100 | **CROSSOVER-FOUND**    | hard     |
| `modular_arithmetic`      | 80/ 80 | 80/100 | 80/100 | LLM-OWNS-THROUGHOUT    | —        |
| `monoid_fold`             | 80/100 |  0/100 |  0/  0 | **CROSSOVER-FOUND**    | medium   |
| `powerset_lattice`        |100/100 | 60/ 80 | 40/ 20 | AMBIGUOUS              | —        |
| `prime_factorization`     |100/100 |100/100 | 60/100 | AMBIGUOUS              | —        |
| `regex_matching`          |100/ 40 | 60/100 | 80/100 | AMBIGUOUS              | —        |
| `set_closure`             |100/100 |100/100 |100/100 | LLM-OWNS-THROUGHOUT    | —        |
| `tropical_semiring`       |100/100 |100/100 | 40/ 60 | AMBIGUOUS              | —        |

Format: `ctrl/treat` percentages. Bold = clean tool win at the named crossover difficulty.

## Territory summary

- **LLM-OWNS-THROUGHOUT**: 5 — combinatorial_counting, graph_reachability, group_theory, modular_arithmetic, set_closure
- **CROSSOVER-FOUND**: 3 — boolean_satisfiability (medium), linear_recurrence (hard), monoid_fold (medium)
- **AMBIGUOUS**: 4 — powerset_lattice, prime_factorization, regex_matching, tropical_semiring
- **TOOL-INTERFERES / TOOL-ASSISTED-THROUGHOUT / CAPABILITY-GAP**: 0

## Per-category interpretation

### CROSSOVER-FOUND (3) — clean tool wins

**`boolean_satisfiability` (crossover at medium):** `0/60` at medium is the strongest signal in the run. Sonnet alone cannot solve 5-variable 3-SAT; with Wile MCP, it gets 60% (3/5). At hard (8 vars), tool advantage shrinks (0 → 20%) but doesn't vanish. Treatment hits the ceiling of brute-force search at hard rather than collapsing — informative about *where* the LLM/Wile boundary actually sits. Of all 12 categories, this is the strongest case for "Wile is essential."

**`linear_recurrence` (crossover at hard):** at hard (order-3, N=80–120), control collapses to 0% — the LLM cannot iterate that many integer-arithmetic steps reliably. Treatment stays at 100% across all three tiers. Clean and clean: tools handle iteration, the LLM doesn't. Wile here is doing exactly what tools are supposed to do.

**`monoid_fold` (crossover at medium, collapses at hard):** medium shows `0/100` — Sonnet alone fails to identify the right monoid operation at scale, but Wile recovers it perfectly. At hard, both arms hit 0%: the problem is output-bound (50 sequences × length 80, both arms run out of output budget before producing the answer). This was predicted in the design doc; the hard tier needs problem redesign, not difficulty extension. Medium is the legitimate boundary.

### LLM-OWNS-THROUGHOUT (5) — Sonnet handles these alone

For all five, Sonnet held ctrl ≥ 70% at every tier, often 100%. The 3-tier range doesn't reach Sonnet's capability ceiling.

**`combinatorial_counting`** (100/100/80): expected. LLMs have combinatorial formulas memorized. At hard (inclusion-exclusion over 4 sets), 80% is the highest control accuracy of any "hard" cell with ctrl < 100% — Sonnet stretches but holds. Calibration target: extend to extra-hard with multinomial / advanced inclusion-exclusion problems.

**`graph_reachability`** (100/100/100): both arms perfect on 5/10/20-vertex graphs. Calibration target: 30–50 vertex graphs with denser cycle structure should start hurting LLM-alone. Wile's `fixpoint`-style iteration scales mechanically.

**`group_theory`** (100/100/100): both arms perfect on S_4/S_5/S_6. The orders involved are small (≤ 6); multi-step composition stays tractable for Sonnet. Calibration target: S_8+, more complex commutators / conjugation chains.

**`modular_arithmetic`** (80/80/100): the only LLM-OWNS category that's *not* at ceiling. Easy/medium ctrl at 80% reflects 4-digit-prime arithmetic that Sonnet sometimes flubs. Treatment at hard (100%) does help, but ctrl stays above the LLM-OWNS floor (70%). Calibration: extend to extra-hard (5–6 digit primes, 14–16 chain length) — this is where ctrl will start dropping.

**`set_closure`** (100/100/100): exactly as predicted by the design-issue flag — every closure equals the entire ring. With prime moduli + additive operation, every starting set generates the whole group, so the answer is trivially `(0 1 ... n-1)`. Sonnet pattern-matches this in seconds. **Needs problem redesign before any meaningful tier extension.** Switching to composite moduli with subgroup-respecting seeds is the obvious fix; deferred to Phase 3.

### AMBIGUOUS (4) — interesting structure to investigate

**`powerset_lattice`** (100/100, 60/80, **40/20**): the only category where treatment *hurts* on a measured cell. At hard, ctrl=40% but treat=20% — a 2-problem flip but consistent with the n=30 algebra-accuracy beta where Wile occasionally went off-trajectory on dense lattice expressions. Worth investigating with deeper sampling at hard (n=15–30); this may be the cleanest "tools confuse the model" signal in the map.

**`prime_factorization`** (100/100, 100/100, 60/100): Sonnet handles factoring up to 5 digits well; at 6–7 digit semiprimes, ctrl drops to 60% and treatment recovers to 100%. Doesn't quite hit the CROSSOVER-FOUND threshold (ctrl needs to be < 50%). Calibration: extend to extra-hard with 8–9 digit semiprimes — that's where ctrl should drop further and the crossover becomes formal.

**`regex_matching`** (**100/40**, 60/100, 80/100): the most surprising shape in the map. At easy (literal match, alternation, kleene-star), tool access *cuts* accuracy from 100% to 40%. At medium and hard, treatment recovers and exceeds control. This is a **tool-interference signal at low difficulty** that flips into tool-assistance at higher difficulty. Hypothesis: on trivial regex problems, Sonnet over-engineers when given tools — calls eval to "verify" the regex, doesn't get a useful response (the scheme oracle is a precomputed answer literal), and second-guesses its initial correct answer. Investigating this single cell may be the most informative thing in the report.

**`tropical_semiring`** (100/100, 100/100, 40/60): clean monotone decline at hard. The +20pp delta at hard is right at the CROSSOVER threshold but ctrl=40% just misses the ctrl-ceiling. At extra-hard (deeper trees) this becomes a formal CROSSOVER-FOUND with high probability. Calibration: extend to extra-hard, expect ctrl to drop to ~10% and treat to ~80%+.

## Calibration implications for Phase 3 (5-tier expansion)

Five categories need extra-hard / super-hard tiers to find their LLM/Wile boundary on Sonnet:

| Category | Current state | Suggested extension |
|----------|--------------|---------------------|
| `combinatorial_counting` | hard 80/80 | extra-hard: 4-set inclusion-exclusion + multinomial; expect ~50/80 |
| `graph_reachability` | 100/100 throughout | extra-hard: 40-vertex graph, 80 edges; expect ~50/100 |
| `group_theory` | 100/100 throughout | extra-hard: S_8 commutators, double commutators; expect ~30/90 |
| `modular_arithmetic` | hard 80/100 | extra-hard: 6-digit primes, 14-step chain; expect ~40/100 |
| `tropical_semiring` | hard 40/60 | extra-hard: depth-5 tree, ~25 values; expect ~10/80 |

Two categories need **problem redesign** before tier expansion is meaningful:

- `set_closure`: switch to composite moduli (12, 15, 20) + subgroup-respecting seeds. Without this, every problem closes to the whole ring and no tier produces signal.
- `monoid_fold/hard`: the 50×80 sequences are output-bound, not capability-bound. Drop to 25×40 at hard and add a real extra-hard at 35×50. This makes hard discriminate between Sonnet's reasoning capability and Wile's pure computation, instead of measuring output capacity.

One category benefits from **deeper sampling at the existing hard tier** rather than tier extension:

- `powerset_lattice/hard` at n=15–30 to verify whether the -20% delta is signal or noise. The 2-problem flip at n=5 is the largest "tool interferes" signal but n=5 makes it indistinguishable from sampling error.

## Anomalies worth a single-cell deep dive

1. **`regex_matching/easy` (-60%)**: investigate the per-problem traces. Hypothesis: tool availability triggers over-engineering. If confirmed, this is a generic finding about LLM tool use, not specific to regex.

2. **`monoid_fold/hard` (0/0 budget-bound)**: the third occurrence of this pattern (Opus alpha, Opus beta, Sonnet capability map). The hard preset's problem size is wrong for this benchmark.

3. **`boolean_satisfiability/hard` (0/20)**: the only crossover category where treatment also struggles. At 8 vars with brute-force enumeration in Scheme, the oracle finishes fast but the LLM still has to guide tool use. May indicate that tool access without algorithmic guidance has limits even for tractable computational problems.

## Cross-cutting observations

**LLMs handle "structure recognition" better than expected on Sonnet.** Group theory, tropical semiring (medium), monoid fold (easy/medium with tools): all show that Sonnet correctly maps named operations to their actual behavior. The structure-recognition probe doesn't break Sonnet at the difficulties tested.

**LLMs fail "iteration to convergence" cleanly.** Linear recurrence (hard) shows the textbook pattern: ctrl collapses as iteration count grows, treatment holds at 100%. This is the most reproducible LLM/tool boundary in the map.

**LLMs fail "search" rapidly.** Boolean SAT crashes from 60% (easy) to 0% (medium) as variable count goes from 3 to 5. This is a much steeper falloff than for execution-precision categories — the search-space exponent dominates.

**LLMs handle "execution precision" better than execution-pessimistic priors predicted.** Modular arithmetic stays at 80% across easy/medium/hard. Powerset_lattice holds at 100%/60% before dropping at hard. Sonnet has more precision-tracking capacity than the design doc anticipated.

## Next steps

In priority order:

1. **Redesign `set_closure`** with composite moduli + subgroup-respecting seeds. ~30 min implementation, regenerate just that category, re-run those 15 problems on Sonnet (~5 min).
2. **Redesign `monoid_fold/hard`** for capability-bound rather than output-bound. ~15 min implementation, regenerate, re-run 5 problems.
3. **Investigate `regex_matching/easy`** — read through the 5 treatment traces, look for what the model does that the control arm doesn't. Likely a 30-min code dive.
4. **Extend the 5 LLM-OWNS categories to extra-hard** per the calibration table above. Each generator needs new tier presets; the harness handles ragged tier coverage already.
5. **Re-run on Sonnet at the expanded set** to lock in the 5-tier capability map. ~50 min wall time.
6. **(Optional) Run on Opus 4.7** with the expanded set. The Opus map should show several boundaries shifted right (Opus stronger than Sonnet on most categories) — interesting cross-model comparison.

The capability map's first complete pass landed cleanly. 8 of 12 categories produced informative signal at the 3-tier range tested; 4 remain ambiguous and want either more samples or tier extension to resolve. No category is so broken that the map collapses; the design proved out at pilot scale.
