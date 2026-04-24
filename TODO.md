# TODO

## Harness refinements

### Prefill continuation for control arm

Currently `run_control` in `algebra-accuracy/evaluate.py` uses a single API call
with a large `max_tokens`. This is option (a) in the budget-calibration design:
simple, equivalent in outcome to a realistic user workflow up to the budget.

Option (b) — **prefill continuation** — is worth exploring later:
- If `stop_reason == "max_tokens"`, append the partial assistant response as
  `{"role": "assistant", "content": partial_text}` and re-invoke.
- The model treats the partial as a prefill and continues from it.
- Closer to what a user would actually do when hitting a cap.
- Edge cases: ensuring the continuation merges cleanly with the partial
  (mid-word, mid-number, mid-code-block boundaries).

Rough cost: ~30 lines vs ~5 for option (a). Worth revisiting if we want to
simulate realistic user behavior, or if we see evidence that large single-call
generations degrade in quality compared to multi-call continuations of the
same total length.

### Budget-isolation experiment for treatment arm

The 2026-04-19 gradient run (`gradient_results_v2_fixed.json`, 90 problems,
claude-opus-4-7) produced a headline treatment delta of **-6%**, but the
per-stop-reason breakdown suggests the signal is confounded:

| Arm | end_turn correct/total | max_tokens (0 correct) | tool_use (cut off) | in-tok/q |
|-----|------------------------|------------------------|---------------------|----------|
| Control | 64/74 (86.5%) | 26 | — | 3,191 |
| Treatment | 56/61 (91.8%) | 21 | 8 | 26,222 |

When the treatment session **completes cleanly** (`end_turn`), it is *more*
accurate than control on matched problems. The overall negative delta is
driven by:

1. Treatment uses ~8x input tokens per query (tool messages fill context).
2. This leaves less output budget for the final answer.
3. `max_tokens` is fatal on either arm (0/26 control, 0/21 treatment correct).
4. Treatment adds 8 additional `tool_use` cut-offs that control can't have.

Case `pset-hard-007` illustrates the mechanism: 6 rounds, model re-defines
helper functions each round, uses an `apropos` round to discover `filter`,
wastes a round on a malformed tool call, hits `max_tokens` before producing
a final answer. The reasoning was progressing; the budget ran out.

**Two variables are currently conflated:**

- (A) tool orchestration consumes context budget
- (B) tools interfere with LLM reasoning

Before expanding the benchmark to probe deeper for a failure boundary, run a
variant that isolates (A) so the residual signal is closer to (B).

**Proposed minimal experiment** (Option α, cheapest):

Re-run the same 90 problems on the treatment arm only, with `max_tokens`
raised (e.g., 2x current). Do not change the control arm. Compare:

| Metric | Current | Predicted if (A) dominates | Predicted if (B) dominates |
|--------|---------|----------------------------|----------------------------|
| Treatment accuracy | 62% | Recovers to ≥ control (68%+) | Stays near 62% |
| Treatment max_tokens count | 21 | Drops sharply | Only small drop |
| Treatment end_turn accuracy | 91.8% | Stays ~91.8% | Stays ~91.8% |

If accuracy recovers to parity-or-better, the thesis that "the LLM can use
the tools well when given room" is supported, and future benchmarks should
budget-match the arms. If accuracy stays flat, orchestration genuinely
interferes with reasoning and the benchmark signal is on a real phenomenon,
not a budget artifact.

**Option β** (more invasive): cache or summarize tool output server-side so
it doesn't re-enter the LLM context on each round. Requires harness changes.
Don't pursue until α results are in.

**Option γ** (already tracked above): prefill continuation for treatment arm
parallel to the control-arm variant. Deferred.

Rough cost: α is ~5 lines (one `max_tokens` constant) + a re-run of the
existing 90 problems. ~1 hour of compute given current tokens/time.
Results are directly comparable to `gradient_results_v2_fixed.json`.

**Dependency note:** interpretation of any deeper "failure boundary" probe
assumes the budget confound is either ruled out or accounted for. Running
the deeper probe first and then α second gives two datasets whose combined
interpretation is harder; running α first is the cheaper sequencing.
