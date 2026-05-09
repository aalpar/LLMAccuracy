# LLMAccuracy

A/B benchmarks measuring Claude's mathematical-reasoning accuracy with and without [Wile](https://github.com/aalpar/wile) — a Scheme interpreter exposing an algebra library via MCP.

## Research question

For each category of mathematical problem, where is the boundary between "the LLM can solve it alone" and "the LLM needs a tool"? Two sub-projects probe this from different angles:

- **`algebra-accuracy/`** — measures per-cell A/B deltas at calibrated difficulty. Tightly focused on a few abstract-algebra categories (powerset lattices, tropical semiring, monoid folds). Statistically rigorous (n=30+ per cell).
- **`capability-map/`** — classifies whole *territories* of mathematical reasoning across 12 categories at three difficulty tiers (easy/medium/hard). Shallow per-cell sampling (n=5), broad coverage. The map labels each category by curve shape: LLM-OWNS-THROUGHOUT, CROSSOVER-FOUND, TOOL-INTERFERES, etc.

The same A/B harness (`algebra-accuracy/evaluate.py`) drives both. Control runs the LLM alone; treatment gives it Wile MCP tools (`eval`, `apropos`, `doc`).

## Layout

```
algebra-accuracy/    Active A/B harness + canonical results
  evaluate.py          A/B benchmark runner (asyncio worker pool, MCP per worker)
  generate.py          Problem generators (4 algebra categories)
  grade.py             IEEE-754 LCD-based grading for decimal answers
  analyze_gradient_results.py  Per-cell classifier
  gradient_problems_n30.json   n=30 problem set
  gradient_results_alpha.json  Alpha run (max_rounds=10 baseline)
  gradient_results_beta.json   Beta run (max_rounds=30, n=30)
  tests/                pytest harness for completion enum, parallel scheduler, analyzer

capability-map/      12-category capability map sister-project
  generate_capability_problems.py  Generators (4 reused + 6 new + 2 hybrid oracles)
  capability_problems.json         180-problem set (12 cats × 3 diffs × 5)
  capability_results.json          Pilot results
  tests/

memory/              Archive: occasional-use tooling + historical run outputs
  arithmetic_generate.py          Decimal-division benchmark (sister project)
  calibrate_*.py                  Difficulty / budget calibration scripts
  gradient_results_v2_fixed.json  The run that motivated alpha/beta
  sonnet_treatment_gradient.json  Non-regenerable Sonnet 4.6 data

docs/plans/          Design docs and reports
docs/learn/          Background notes
```

## Design documents

The project's research framing and design decisions are documented progressively. Read in order if you want the narrative; jump to the latest if you just want the current state.

| Document | What it covers |
|----------|----------------|
| [Capability-map architecture](docs/plans/2026-04-19-capability-map-design.md) | Directory layout, harness reuse, curve-based per-category classifier, 3-tier difficulty sweep |
| [Per-category content](docs/plans/2026-04-19-capability-map-categories.md) | What each of the 12 categories tests, why it's a useful probe, expected boundary, example problems per tier |
| [Sonnet-coverage implementation plan](docs/plans/2026-04-21-sonnet-coverage-plan.md) | Step-by-step plan for completing the 12 generators and running the first full capability map on Sonnet 4.6 |
| [n=30 calibrated-cells plan](docs/plans/2026-04-19-calibrated-cells-n30.md) | Earlier work: harness rewrite (completion enum, max_rounds CLI, parallelism) + n=30 re-run on 3 calibrated algebra cells |
| [n=30 calibrated-cells report](docs/plans/2026-04-19-calibrated-cells-n30-report.md) | Results: round-cap confound identified, +23% treatment delta on `powerset_lattice/hard` after fix |
| [Ultra-hard difficulty design](docs/plans/2026-03-29-ultra-hard-difficulty-design.md) | Earlier difficulty calibration work (mostly historical) |

## How the A/B harness works

```
                ┌──────────────────────────────────────┐
                │  problems.json (per-problem records) │
                └────────────────┬─────────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │  evaluate.py             │
                    │  (asyncio worker pool)   │
                    └─────┬──────────────┬─────┘
                          │              │
                ┌─────────▼──┐    ┌──────▼─────────┐
                │  Control   │    │  Treatment     │
                │  LLM only  │    │  LLM + Wile    │
                └─────────┬──┘    │  MCP tools     │
                          │       └──────┬─────────┘
                          │              │
                          └──────┬───────┘
                                 │
                                 ▼
                ┌──────────────────────────────────────┐
                │  results.json + completion enum      │
                │  (end_turn, max_tokens,              │
                │   max_rounds, budget_exhausted)      │
                └────────────────┬─────────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │  analyze_*.py            │
                    │  Per-cell classification │
                    └──────────────────────────┘
```

Each problem record carries a Wile-computable `scheme_expression` so ground-truth answers are deterministic. The grader compares the LLM's extracted answer (last `ANSWER:` line) against ground truth using type-aware equality (`integer`, `set`, `polynomial`, `permutation`, `decimal`-with-precision, `string`).

## Setup

Requires Python 3.10, 3.11, or 3.12 and a [Wile](https://github.com/aalpar/wile) binary in `/usr/local/bin/wile` (or pass `--wile <path>` on every command).

```bash
# Create and activate a virtualenv (any of python3.10 / 3.11 / 3.12 work)
python3.12 -m venv .venv
source .venv/bin/activate

# Install runtime + test dependencies
pip install -r requirements.txt

# Confirm tests collect and pass
cd algebra-accuracy && python3 -m pytest -v
cd ../capability-map && python3 -m pytest -v
```

For benchmark runs, set `ANTHROPIC_API_KEY` in the shell:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Running the harness

Generate problems:

```bash
python algebra-accuracy/generate.py \
    --wile /usr/local/bin/wile \
    --output algebra-accuracy/problems.json
```

Run A/B benchmark:

```bash
ANTHROPIC_API_KEY=... python algebra-accuracy/evaluate.py \
    --problems algebra-accuracy/problems.json \
    --output algebra-accuracy/results.json \
    --model claude-sonnet-4-6 \
    --wile /usr/local/bin/wile \
    --condition both \
    --workers 4 \
    --max-rounds 30 \
    --total-budget 10000
```

Analyze:

```bash
python algebra-accuracy/analyze_gradient_results.py \
    --results algebra-accuracy/results.json
```

For the capability map, swap `algebra-accuracy/generate.py` for `capability-map/generate_capability_problems.py` and the analyzer for one specific to the curve-shape classifier (in progress per the [Sonnet-coverage plan](docs/plans/2026-04-21-sonnet-coverage-plan.md)).

## Status

Active research project. Public for transparency and reproducibility. No stability guarantees — APIs and problem sets evolve as findings come in.

## License

[MIT](LICENSE)
