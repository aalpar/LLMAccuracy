# Calibrated-Cells n=30 Re-Run — Report

## Setup

- **Problems:** 90 fresh problems in `gradient_problems_n30.json`, seed 2026, 3 cells × n=30.
- **Cells:** `powerset_lattice/medium`, `powerset_lattice/hard`, `tropical_semiring/hard` — the three CALIBRATED cells from the alpha run.
- **Harness settings:** `--max-rounds 30 --total-budget 10000 --workers 4 --condition both`.
- **Model:** `claude-opus-4-7`.
- **Wall time:** ~100 min at workers=4 (serial equivalent ~200 min).
- **Output:** `gradient_results_beta.json`.
- **Harness changes since alpha:** replaced `truncated` boolean with `completion` enum (`end_turn, max_tokens, max_rounds, budget_exhausted`); exposed `max_rounds` as a CLI flag (default 30, up from hard-coded 10); parallelized the independent-problem loop.

## Results at n=30

| Cell | n | Ctrl | Treat | Δ | Treat round-cap rate | Classification |
|------|---|------|-------|---|---------------------|----------------|
| `powerset_lattice/medium` | 30 | 93% | 90% | -3% | 0% | MIXED |
| `powerset_lattice/hard`   | 30 | 33% | 57% | **+23%** | 3% | CALIBRATED |
| `tropical_semiring/hard`  | 30 | 93% | 83% | -10% | 0% | MIXED |
| **Total**                 | 90 | 73% | 77% | +3% | 1% | — |

## Alpha vs. Beta Comparison

Same three cells, alpha (n=10, max_rounds=10, ctrl budget=5k, treat budget=10k) vs beta (n=30, max_rounds=30, ctrl budget=10k, treat budget=10k):

| Cell | alpha Δ | beta Δ | Swing |
|------|---------|--------|-------|
| `powerset_lattice/medium` | -10% | -3% | +7% |
| `powerset_lattice/hard`   | **-20%** | **+23%** | **+43%** |
| `tropical_semiring/hard`  | +40% | -10% | -50% |

Two confounds distorted alpha's numbers:

1. **Round-cap (`max_rounds=10`):** 9/10 `powerset_lattice/hard` treatment failures in alpha ended with `stop_reason=tool_use` and tokens well under budget — the harness cut them off mid-dialog. Beta raises the cap to 30; only 3% of beta treatment runs hit it.

2. **Unequal control budget:** alpha gave control `max_tokens=5000` (single call) while treatment got `total_budget=10000` (cumulative). Six of ten control runs on `powerset_lattice/hard` in alpha ended at `max_tokens`. Beta uses 10k for both arms — control's measured accuracy on easier cells jumps substantially, not because the model got smarter but because we stopped truncating it.

## Statistical caveat

At n=30, single-cell deltas are underpowered:

| Cell | Observed Δ | Fisher exact (two-tail) |
|------|-----------|-------------------------|
| `powerset_lattice/medium` | -3% | p = 1.00 |
| `powerset_lattice/hard`   | +23% | p = 0.12 |
| `tropical_semiring/hard`  | -10% | p = 0.42 |

None reach p<0.05. `powerset_lattice/hard` is the only cell with a plausibly real effect (+23% is a large observed delta; the p-value reflects sample size, not absence of effect). Reaching p<0.05 on a +23% effect at baseline=33% requires n≈50–60 per cell.

## Completion-mode breakdown (treatment arm)

| Cell | end_turn | max_tokens | max_rounds | budget_exhausted |
|------|---------:|-----------:|-----------:|-----------------:|
| `powerset_lattice/medium` | 30 | 0 | 0 | 0 |
| `powerset_lattice/hard`   | 23 | 1 | 1 | 5 |
| `tropical_semiring/hard`  | 28 | 0 | 0 | 2 |

`powerset_lattice/hard` still has 6/30 treatment non-completions — mostly budget-bound (5), not round-capped. With the round-cap fixed, the residual failures on this cell are driven by the cumulative output budget, not orchestration.

## Interpretation

**What changed from alpha:**

- The -20% on `powerset_lattice/hard` was a round-cap artifact. Raising `max_rounds` from 10 to 30 flipped the delta to +23%. The cell now measures what it was supposed to measure.
- The +40% on `tropical_semiring/hard` was partly a control-budget artifact. When control gets the same 10k budget as treatment, its accuracy rises from 30% to 93% on these arithmetic-heavy problems.

**What the beta data suggests (not yet rigorous):**

- On hard lattice reasoning, tool access helps meaningfully (+23%, p=0.12 at n=30). The model uses ~10 tool rounds on average, and needs that headroom to iterate helper functions to convergence.
- On easier cells (`powerset/medium`, `tropical/hard`) where control is already ≥90%, tool access doesn't add value and may introduce small regressions. Those deltas are within the noise envelope at this sample size.
- Overall treatment vs control at +3% is small and not the main story. The per-cell pattern is more informative than the aggregate.

## Next step (if the claim matters)

To convert the `powerset_lattice/hard` +23% observation from "suggestive" to "significant" at p<0.05, re-run just that cell at n=60. Estimated compute: ~20 min at workers=4.

If instead the goal is broad coverage across algebraic structures, this re-run has already served its purpose: the harness is now free of the round-cap and unequal-budget confounds, and future runs will produce directly interpretable deltas.

## Residual concerns

1. **Treatment input tokens are ~40× control input tokens** (82k vs 2k per question), but `cache_read=0` in the run summary. Cache control is set on the system prompt only; tool-result messages reload the full context each round. Implementing prompt caching on tool results (or server-side summarization) would reduce treatment's effective budget pressure. Not needed for this analysis; flagged for later.
2. **`tropical_semiring/hard` treatment underperformance** is small (3 flipped problems) but in the unexpected direction. If it replicates at n=60, worth investigating whether the model is invoking tools unnecessarily on problems it could solve in-head.
