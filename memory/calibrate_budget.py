#!/usr/bin/env python3
"""Token Budget Calibration — sample treatment runs to size a shared budget.

Runs the treatment condition (LLM + Wile MCP) on a small sample of problems
per difficulty tier and records `output_tokens` per problem. Produces a JSON
summary with per-tier median and p95, which feeds the budget formula used by
evaluate.py for both control and treatment arms.

The single number we care about per tier is `p95_output_tokens`: the 95th
percentile of total (across-rounds) output tokens treatment actually spends.
Pick `total_budget = K * p95` where K is a safety multiplier (2x is sensible;
you decide after seeing the numbers).

Usage:
    python algebra-accuracy/calibrate_budget.py \\
        --problems algebra-accuracy/arithmetic_problems.json \\
        --samples 5 --seed 42 \\
        --model claude-opus-4-7 \\
        --output algebra-accuracy/calibration_results.json
"""

import argparse
import json
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

try:
    import anthropic
except ImportError:
    print("Install the Anthropic SDK: pip install anthropic", file=sys.stderr)
    sys.exit(1)

# Reuse evaluate.py's MCP wiring and treatment runner verbatim so calibration
# measures the *same* code path the benchmark uses. If run_treatment's per-round
# cap changes, calibration tracks it automatically.
# Tooling lives in memory/ (occasional-use) but reuses the harness in
# algebra-accuracy/. Both paths go on sys.path so cross-imports resolve.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "algebra-accuracy"))
from evaluate import (  # noqa: E402
    WileMCPSession,
    answers_match,
    detect_wile,
    mcp_tools_to_anthropic,
    run_treatment,
)


def sample_by_tier(problems: List[dict], samples_per_tier: int, rng: random.Random) -> Dict[str, List[dict]]:
    """Group problems by `difficulty`, then sample up to N per group."""
    by_tier: Dict[str, List[dict]] = defaultdict(list)
    for p in problems:
        by_tier[p["difficulty"]].append(p)

    sampled: Dict[str, List[dict]] = {}
    for tier, group in by_tier.items():
        n = min(samples_per_tier, len(group))
        sampled[tier] = rng.sample(group, n)
    return sampled


def summarize(samples: List[dict]) -> dict:
    """Reduce a list of sample-result dicts to tier-level statistics.

    Token stats are computed over *successful* samples only. A failed run's
    token count is uninterpretable for budget sizing — it measures how much
    the model spent before giving up, not how much a correct answer costs.
    """
    toks = [s["output_tokens"] for s in samples]
    toks_sorted = sorted(toks)
    # p95 via nearest-rank; statistics.quantiles would interpolate, which
    # obscures the actual observed maximum when n is small.
    p95_index = min(len(toks_sorted) - 1, max(0, int(round(0.95 * (len(toks_sorted) - 1)))))

    correct_samples = [s for s in samples if s.get("correct")]
    correct_toks = [s["output_tokens"] for s in correct_samples]
    correct_toks_sorted = sorted(correct_toks)
    correct_p95_index = min(len(correct_toks_sorted) - 1, max(0, int(round(0.95 * (len(correct_toks_sorted) - 1))))) if correct_toks_sorted else 0

    return {
        "n": len(samples),
        "n_correct": len(correct_samples),
        "output_tokens": {
            "min": min(toks),
            "median": int(statistics.median(toks)),
            "p95": toks_sorted[p95_index],
            "max": max(toks),
        },
        "output_tokens_correct_only": (
            {
                "min": min(correct_toks),
                "median": int(statistics.median(correct_toks)),
                "p95": correct_toks_sorted[correct_p95_index],
                "max": max(correct_toks),
            }
            if correct_toks
            else None
        ),
        "rounds": {
            "min": min(s["rounds"] for s in samples),
            "median": int(statistics.median(s["rounds"] for s in samples)),
            "max": max(s["rounds"] for s in samples),
        },
        "elapsed_s": {
            "median": round(statistics.median(s["elapsed_s"] for s in samples), 2),
            "max": round(max(s["elapsed_s"] for s in samples), 2),
        },
        "samples": samples,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--problems", type=Path, required=True, help="Path to problems JSON")
    ap.add_argument("--samples", type=int, default=5, help="Samples per difficulty tier")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for sampling")
    ap.add_argument("--model", default="claude-opus-4-7", help="Anthropic model ID")
    ap.add_argument("--wile", type=Path, help="Path to Wile binary (auto-detected if omitted)")
    ap.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).parent / "calibration_results.json",
        help="Output JSON path",
    )
    args = ap.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        ap.error("ANTHROPIC_API_KEY not set")

    problems = json.loads(args.problems.read_text())
    if not problems:
        ap.error(f"No problems in {args.problems}")

    rng = random.Random(args.seed)
    sampled = sample_by_tier(problems, args.samples, rng)

    wile_bin = detect_wile(args.wile)
    session = WileMCPSession(wile_bin)
    try:
        tools = mcp_tools_to_anthropic(session.list_tools())
        client = anthropic.Anthropic()

        tier_results: Dict[str, dict] = {}
        total_problems = sum(len(v) for v in sampled.values())
        done = 0

        for tier in sorted(sampled.keys()):
            print(f"\n── Tier: {tier} ({len(sampled[tier])} samples) ──", flush=True)
            samples: List[dict] = []
            for problem in sampled[tier]:
                done += 1
                print(f"  [{done}/{total_problems}] {problem['id']} ... ", end="", flush=True)
                t0 = time.perf_counter()
                # Fresh Scheme session per problem so state from the previous
                # problem can't carry over and skew the token count.
                session.reset()
                result = run_treatment(client, args.model, problem, session, tools)
                elapsed = time.perf_counter() - t0
                # Grade against ground truth so calibration distinguishes
                # "cost of successful treatment" from "cost of a failed run".
                correct = answers_match(
                    result["extracted_answer"],
                    problem["answer"],
                    problem.get("answer_type", "integer"),
                    problem.get("precision"),
                )
                samples.append({
                    "id": problem["id"],
                    "output_tokens": result["output_tokens"],
                    "input_tokens": result["input_tokens"],
                    "rounds": result.get("rounds", 1),
                    "tool_calls": result.get("tool_calls", 0),
                    "elapsed_s": round(elapsed, 3),
                    "extracted_answer": result["extracted_answer"],
                    "correct": correct,
                })
                print(
                    f"out={result['output_tokens']} tok, "
                    f"rounds={result.get('rounds', 1)}, "
                    f"{elapsed:.1f}s, "
                    f"correct={correct}",
                    flush=True,
                )
            tier_results[tier] = summarize(samples)

        output = {
            "model": args.model,
            "problems_file": str(args.problems),
            "samples_per_tier": args.samples,
            "seed": args.seed,
            "tiers": tier_results,
        }
        args.output.write_text(json.dumps(output, indent=2) + "\n")

        # Human-readable summary
        print(f"\n── Calibration summary (wrote {args.output}) ──")
        for tier in sorted(tier_results.keys()):
            s = tier_results[tier]
            t = s["output_tokens"]
            tc = s.get("output_tokens_correct_only")
            print(
                f"  {tier:12s}  n={s['n']} (correct={s['n_correct']}/{s['n']})  "
                f"all: median={t['median']:5d} p95={t['p95']:5d} max={t['max']:5d}"
            )
            if tc:
                print(
                    f"  {'':12s}  correct-only: "
                    f"median={tc['median']:5d} p95={tc['p95']:5d} max={tc['max']:5d}"
                )
        print(
            "\nSuggested total_budget = K * p95(correct-only). "
            "K=2 is a sensible default."
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
