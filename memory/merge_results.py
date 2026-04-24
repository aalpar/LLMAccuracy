#!/usr/bin/env python3
"""Merge two evaluate.py results files keyed by problem id.

Use case: Option α isolation experiment — keep control results from a prior
run, replace treatment results with a re-run at higher budget. Produces a
single combined file that analyze_gradient_results.py can consume.

Usage:
    python algebra-accuracy/merge_results.py \\
        --base algebra-accuracy/gradient_results_v2_fixed.json \\
        --overlay algebra-accuracy/treatment_only_10k.json \\
        --condition treatment \\
        --output algebra-accuracy/gradient_results_alpha.json

Semantics: for each problem id in `overlay`, replace that problem's
`{condition}` and `{condition}_correct` fields in the base record with the
overlay record's values. Problem ids not in overlay are left as-is. The
output file has the same length as `base`.
"""

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", type=Path, required=True, help="File whose structure is preserved")
    ap.add_argument("--overlay", type=Path, required=True, help="File whose condition data overrides")
    ap.add_argument("--condition", choices=["control", "treatment"], required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    base = json.loads(args.base.read_text())
    overlay = {r["id"]: r for r in json.loads(args.overlay.read_text())}

    correctness_key = f"{args.condition}_correct"
    merged_count = 0
    for r in base:
        if r["id"] in overlay:
            ov = overlay[r["id"]]
            if args.condition in ov:
                r[args.condition] = ov[args.condition]
                if correctness_key in ov:
                    r[correctness_key] = ov[correctness_key]
                merged_count += 1

    args.output.write_text(json.dumps(base, indent=2) + "\n")
    print(f"Merged {merged_count}/{len(base)} problems' {args.condition} data.")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
