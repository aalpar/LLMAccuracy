#!/usr/bin/env python3
"""Algebra Accuracy Benchmark — A/B Evaluation Harness

Runs each problem in two conditions:
  Control:   LLM answers without tools (reasoning only)
  Treatment: LLM has access to Wile's MCP tools (eval, doc, apropos, etc.)

Requires: ANTHROPIC_API_KEY environment variable, `pip install anthropic`

Usage:
    python algebra-accuracy/evaluate.py --problems problems.json
    python algebra-accuracy/evaluate.py \
        --problems problems.json --model claude-sonnet-4-6 --condition both
"""

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from collections import defaultdict
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, getcontext
from fractions import Fraction
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("Install the Anthropic SDK: pip install anthropic", file=sys.stderr)
    sys.exit(1)


REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Import the LCD machinery from the sibling grade.py so the pass criterion
# has a single source of truth. Adding this file's directory to sys.path
# lets `from grade import ...` work regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from grade import is_pass, leading_correct_digits  # noqa: E402

# IEEE-754 §4.3.1 roundTiesToEven — matches arithmetic_generate.py and grade.py.
# Set once at module load; every Decimal operation in this module inherits it.
getcontext().prec = 200
getcontext().rounding = ROUND_HALF_EVEN


# ── System Prompts ───────────────────────────────────────────────
#
# These are the single most impactful parameter in the benchmark.
#
# The CONTROL prompt determines how hard the LLM tries to compute
# on its own. The TREATMENT prompt is minimal — the model discovers
# Wile's algebra API through the MCP doc/apropos tools at runtime.

CONTROL_SYSTEM_PROMPT = """\
You are solving algebra problems. Work through each problem step by step, \
showing your reasoning. Give your final answer on the LAST line in this \
exact format:

ANSWER: <value>

For fractions, give the answer in lowest terms (e.g., 7/12).
For integers, give just the number (e.g., 42).
Do not include units, variable names, or extra text on the answer line.\
"""

TREATMENT_SYSTEM_PROMPT = """\
You are solving algebra problems. You have access to the Wile Scheme \
interpreter via tools. The interpreter includes an algebra library \
(wile algebra). Use the doc and apropos tools to look up function \
signatures before computing with eval.

Give your final answer on the LAST line in this exact format:

ANSWER: <value>

For fractions, give the answer in lowest terms (e.g., 7/12).
For integers, give just the number (e.g., 42).\
"""


# ── Wile MCP Session ─────────────────────────────────────────────


def detect_wile(hint=None):
    """Find the Wile binary."""
    if hint:
        p = Path(hint)
        if p.is_file() and os.access(p, os.X_OK):
            return p
        raise FileNotFoundError(f"Not found: {hint}")

    os_name = platform.system().lower()
    machine = platform.machine()
    arch = "amd64" if machine == "x86_64" else machine

    for candidate in [
        REPO_ROOT / "dist" / os_name / arch / "wile",
        REPO_ROOT / "dist" / "wile",
    ]:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate

    raise FileNotFoundError("Wile binary not found. Run 'make build' first.")


class WileMCPSession:
    """Manages a Wile MCP server subprocess over stdio JSON-RPC."""

    def __init__(self, wile_binary, timeout=30):
        self.proc = subprocess.Popen(
            [str(wile_binary), "--mcp", f"--mcp-timeout={timeout}"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._id = 0
        self._initialize()

    def _next_id(self):
        self._id += 1
        return self._id

    def _request(self, method, params=None):
        """Send a JSON-RPC request and return the result."""
        req_id = self._next_id()
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("Wile MCP server closed unexpectedly")
            resp = json.loads(line)
            if "id" in resp and resp["id"] == req_id:
                if "error" in resp:
                    raise RuntimeError(
                        f"MCP error: {resp['error'].get('message', resp['error'])}"
                    )
                return resp["result"]
            # Skip notifications

    def _notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def _initialize(self):
        result = self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "algebra-benchmark", "version": "1.0"},
        })
        self._notify("notifications/initialized")
        return result

    def list_tools(self):
        """Return the MCP tool definitions."""
        return self._request("tools/list")["tools"]

    def call_tool(self, name, arguments):
        """Call an MCP tool and return the text result."""
        result = self._request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })
        texts = []
        for item in result.get("content", []):
            if item.get("type") == "text":
                texts.append(item["text"])
        output = "\n".join(texts) or "(no output)"
        if result.get("isError"):
            return f"Error: {output}"
        return output

    def reset(self):
        """Reset the Scheme session to a clean state."""
        self.call_tool("reset", {})

    def close(self):
        """Shut down the MCP server."""
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def mcp_tools_to_anthropic(mcp_tools):
    """Convert MCP tool definitions to Anthropic API tool format."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["inputSchema"],
        }
        for t in mcp_tools
    ]


# ── Answer Extraction & Comparison ──────────────────────────────


def extract_answer(text):
    """Extract the ANSWER: value from LLM output (last occurrence)."""
    if not text:
        return None
    matches = re.findall(r"ANSWER:\s*(.+)", text)
    if not matches:
        return None
    raw = matches[-1].strip()
    # Strip trailing parenthetical notes (e.g. "42 (mod 107)") but not
    # answers that ARE parenthesized tuples (e.g. "(0 31)" or "(3 1 2 4)").
    if not raw.startswith("("):
        raw = re.sub(r"\s*\(.*\)\s*$", "", raw)
    raw = re.sub(r"\s*\u2248.*$", "", raw)  # ≈ approximation
    raw = raw.rstrip(".*")
    return raw


def normalize_answer(answer_str, answer_type="integer"):
    """Normalize an answer string for comparison.

    For polynomial and permutation types, strips parentheses and returns
    a tuple of ints so that '(10 9)' and '10 9' compare equal.
    For set types, extracts element names and returns a frozenset so that
    ordering differences don't matter. Handles both Scheme list format
    '(a b c)' and set notation '{a, b, c}'.

    For decimal type, returns a Decimal value. Tolerates digit separators
    (commas, underscores) and scientific notation; rejects values with
    stray non-numeric text.
    """
    if answer_str is None:
        return None
    s = answer_str.strip()

    if answer_type == "set":
        s_clean = s.strip("{}()")
        elements = s_clean.replace(",", " ").split()
        return frozenset(elements)

    if answer_type in ("polynomial", "permutation"):
        s_clean = s.strip("()")
        try:
            return tuple(int(x) for x in s_clean.split())
        except ValueError:
            pass
        return None

    if answer_type == "decimal":
        try:
            return Decimal(s.replace(",", "").replace("_", ""))
        except InvalidOperation:
            return None

    try:
        return Fraction(s)
    except (ValueError, ZeroDivisionError):
        pass
    try:
        return int(s)
    except ValueError:
        pass
    return s


def answers_match(llm_answer, ground_truth, answer_type="integer", precision=None):
    """Compare LLM answer against ground truth.

    For answer_type == "decimal", returns True iff the LLM answer agrees with
    ground truth to `precision` leading significant digits under the pass
    criterion defined in grade.is_pass (IEEE-754 roundTiesToEven). If
    precision is None, it is inferred from the ground-truth digit count.
    """
    norm_llm = normalize_answer(llm_answer, answer_type)
    norm_gt = normalize_answer(ground_truth, answer_type)

    if norm_llm is None:
        return False

    if answer_type == "set":
        return norm_llm == norm_gt

    if answer_type in ("polynomial", "permutation"):
        return norm_llm == norm_gt

    if answer_type == "decimal":
        if not isinstance(norm_llm, Decimal) or not isinstance(norm_gt, Decimal):
            return False
        lcd = leading_correct_digits(norm_llm, norm_gt)
        if precision is None:
            # Infer from the ground-truth significand length.
            gt_digits = str(ground_truth).lstrip("-+").replace(".", "").lstrip("0")
            precision = max(len(gt_digits), 1)
        return is_pass(lcd, precision)

    # Numeric comparison via Fraction handles equivalent representations
    if isinstance(norm_llm, (int, Fraction)) and isinstance(
        norm_gt, (int, Fraction)
    ):
        return Fraction(norm_llm) == Fraction(norm_gt)

    return str(norm_llm) == str(norm_gt)


# ── Completion Status ────────────────────────────────────────────
#
# The Anthropic API's `stop_reason` alone doesn't capture why a tool-using
# run ended. `stop_reason == "tool_use"` means the model wanted another
# tool call — but whether the harness allowed it depends on our budget
# and round caps. We enumerate four terminal states:
#
#   end_turn            — model produced final answer cleanly
#   max_tokens          — final API call hit the per-call token cap
#   budget_exhausted    — cumulative output_tokens reached total_budget
#   max_rounds          — treatment loop hit max_rounds with tool_use pending

COMPLETION_STATES = ("end_turn", "max_tokens", "budget_exhausted", "max_rounds")


def classify_completion(stop_reason: str, budget_hit: bool, rounds_hit: bool) -> str:
    """Classify the terminal state of an evaluation run.

    Precedence when multiple apply:
      budget_exhausted > max_rounds > max_tokens > end_turn

    Budget exhaustion is the hardest cap — it's checked before the loop
    re-enters — so if it fires alongside rounds_hit, budget wins. max_tokens
    is per-call and only matters if nothing more global fired.
    """
    if budget_hit:
        return "budget_exhausted"
    if rounds_hit:
        return "max_rounds"
    if stop_reason == "max_tokens":
        return "max_tokens"
    return "end_turn"


# ── Evaluation Loop ─────────────────────────────────────────────


def run_control(client, model, problem, max_tokens=1024):
    """Run the control condition (no tools).

    `max_tokens` is the single-call budget. When calibration or the main
    harness sets this to the shared total_budget, control gets the same
    rope treatment spends across rounds.
    """
    t0 = time.perf_counter()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=CONTROL_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": problem["natural_language"]}],
    )
    elapsed = time.perf_counter() - t0
    text = "".join(b.text for b in response.content if hasattr(b, "text"))
    completion = classify_completion(
        stop_reason=response.stop_reason,
        budget_hit=False,
        rounds_hit=False,
    )
    return {
        "raw_response": text,
        "extracted_answer": extract_answer(text),
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "stop_reason": response.stop_reason,
        "completion": completion,
        "truncated": completion != "end_turn",
        "total_budget": max_tokens,
        "elapsed_s": round(elapsed, 3),
    }


def run_treatment(
    client,
    model,
    problem,
    mcp_session,
    tools,
    total_budget=5000,
    per_round_cap=5000,
    max_rounds=30,
):
    """Run the treatment condition (with Wile MCP tools).

    `total_budget` caps cumulative output_tokens across rounds. When the
    budget is exhausted, the loop breaks — so treatment and control share
    the same token envelope, making success rates directly comparable.
    """
    messages = [{"role": "user", "content": problem["natural_language"]}]

    full_text = ""
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_creation_tokens = 0
    total_cache_read_tokens = 0
    tool_calls = 0
    tool_trace = []
    rounds = 0
    last_stop_reason = None
    budget_hit = False

    cached_system = [
        {
            "type": "text",
            "text": TREATMENT_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    rounds_hit = False
    t0 = time.perf_counter()
    for round_i in range(max_rounds):
        # Shrink the per-round cap as we approach the total budget so the
        # final round can't overshoot. max_tokens must be >= 1 per the API.
        remaining = total_budget - total_output_tokens
        if remaining <= 0:
            budget_hit = True
            break
        this_cap = max(1, min(per_round_cap, remaining))

        response = client.messages.create(
            model=model,
            max_tokens=this_cap,
            system=cached_system,
            messages=messages,
            tools=tools,
        )
        rounds += 1
        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens
        total_cache_creation_tokens += getattr(response.usage, "cache_creation_input_tokens", 0)
        total_cache_read_tokens += getattr(response.usage, "cache_read_input_tokens", 0)
        last_stop_reason = response.stop_reason

        tool_uses = []
        for block in response.content:
            if hasattr(block, "text"):
                full_text += block.text
            if block.type == "tool_use":
                tool_uses.append(block)

        if not tool_uses:
            break

        tool_calls += len(tool_uses)

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in tool_uses:
            result = mcp_session.call_tool(block.name, block.input)
            tool_trace.append({
                "tool": block.name,
                "arguments": block.input,
                "output": result,
            })
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                }
            )
        messages.append({"role": "user", "content": tool_results})

        if response.stop_reason == "end_turn":
            break
    else:
        # for-else: executed only if the loop didn't break. We exhausted
        # max_rounds iterations with the model still wanting tool use.
        if last_stop_reason == "tool_use":
            rounds_hit = True

    elapsed = time.perf_counter() - t0
    completion = classify_completion(
        stop_reason=last_stop_reason,
        budget_hit=budget_hit,
        rounds_hit=rounds_hit,
    )
    return {
        "raw_response": full_text,
        "extracted_answer": extract_answer(full_text),
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "cache_creation_tokens": total_cache_creation_tokens,
        "cache_read_tokens": total_cache_read_tokens,
        "stop_reason": last_stop_reason,
        "completion": completion,
        "truncated": completion != "end_turn",
        "total_budget": total_budget,
        "elapsed_s": round(elapsed, 3),
        "rounds": rounds,
        "tool_calls": tool_calls,
        "tool_trace": tool_trace,
    }


# ── Summary ──────────────────────────────────────────────────────


def print_summary(results, condition):
    """Print accuracy summary table followed by token/time stats."""
    stats = defaultdict(
        lambda: defaultdict(lambda: {"control": [0, 0], "treatment": [0, 0]})
    )

    for r in results:
        cat, diff = r["category"], r["difficulty"]
        if "control_correct" in r:
            stats[cat][diff]["control"][0] += int(r["control_correct"])
            stats[cat][diff]["control"][1] += 1
        if "treatment_correct" in r:
            stats[cat][diff]["treatment"][0] += int(r["treatment_correct"])
            stats[cat][diff]["treatment"][1] += 1

    def pct(correct, total):
        return f"{100 * correct / total:.0f}%" if total else "n/a"

    print("\n" + "=" * 72)
    print("RESULTS")
    print("=" * 72)

    if condition == "both":
        print(
            f"{'Category':<25} {'Diff':<8} "
            f"{'Control':>9} {'Treatment':>10} {'Delta':>8}"
        )
        print("-" * 72)
    else:
        print(f"{'Category':<25} {'Diff':<8} {'Accuracy':>10}")
        print("-" * 48)

    for cat in sorted(stats):
        for diff in ["easy", "medium", "hard", "extra-hard", "super-hard", "ultra-hard"]:
            if diff not in stats[cat]:
                continue
            s = stats[cat][diff]

            if condition == "both":
                cc, ct = s["control"]
                tc, tt = s["treatment"]
                delta = ""
                if ct and tt:
                    d = 100 * (tc / tt - cc / ct)
                    delta = f"{d:+.0f}%"
                print(
                    f"{cat:<25} {diff:<8} "
                    f"{pct(cc, ct):>9} {pct(tc, tt):>10} {delta:>8}"
                )
            else:
                cond = "control" if condition == "control" else "treatment"
                c, t = s[cond]
                print(f"{cat:<25} {diff:<8} {pct(c, t):>10}")

    # Totals
    n = len(results)
    if condition == "both":
        tc = sum(1 for r in results if r.get("control_correct"))
        tt = sum(1 for r in results if r.get("treatment_correct"))
        print("-" * 72)
        delta = f"{100 * (tt - tc) / n:+.0f}%"
        print(
            f"{'TOTAL':<25} {'all':<8} "
            f"{pct(tc, n):>9} {pct(tt, n):>10} {delta:>8}"
        )
    print("=" * 72)

    # ── Token / time stats ───────────────────────────────────────
    def _tok_stats(cond_key):
        toks_in  = [r[cond_key].get("input_tokens", 0)  for r in results if cond_key in r]
        toks_out = [r[cond_key].get("output_tokens", 0) for r in results if cond_key in r]
        secs     = [r[cond_key].get("elapsed_s", 0)     for r in results if cond_key in r]
        n = len(toks_in)
        if not n:
            return None
        return {
            "n": n,
            "in_total":  sum(toks_in),
            "out_total": sum(toks_out),
            "in_avg":    sum(toks_in)  / n,
            "out_avg":   sum(toks_out) / n,
            "s_total":   sum(secs),
            "s_avg":     sum(secs) / n,
        }

    print("\nTOKEN / TIME SUMMARY")
    print("=" * 72)
    for cond_key, label in [("control", "Control"), ("treatment", "Treatment")]:
        s = _tok_stats(cond_key)
        if s is None:
            continue
        extra = ""
        if cond_key == "treatment":
            tc_avg = sum(r["treatment"].get("tool_calls", 0) for r in results if "treatment" in r) / s["n"]
            rd_avg = sum(r["treatment"].get("rounds", 0)     for r in results if "treatment" in r) / s["n"]
            cache_created = sum(r["treatment"].get("cache_creation_tokens", 0) for r in results if "treatment" in r)
            cache_read    = sum(r["treatment"].get("cache_read_tokens", 0)     for r in results if "treatment" in r)
            extra = (
                f"  tool_calls/q={tc_avg:.1f}  rounds/q={rd_avg:.1f}"
                f"  cache_write={cache_created:,} cache_read={cache_read:,}"
            )
        print(
            f"{label:<12}  in={s['in_avg']:.0f} tok/q ({s['in_total']:,} total)"
            f"  out={s['out_avg']:.0f} tok/q ({s['out_total']:,} total)"
            f"  {s['s_avg']:.1f}s/q ({s['s_total']:.0f}s total){extra}"
        )
    print("=" * 72)


# ── Session Evaluation ───────────────────────────────────────────
#
# Session mode runs all problems in a single conversation. Each problem
# is appended as a new user turn; prior exchanges remain in context.
# This lets errors (and corrections) compound across problems, which is
# a realistic model of how LLMs are used in practice.
#
# Token cost is O(N²) in session length because the full history is
# re-submitted on every call. Track per-problem input_tokens to see
# the accumulation directly.


def run_control_session(client, model, problems, delay, total_budget=5000):
    """Run all problems in a single control conversation."""
    messages = []
    results = []

    for j, problem in enumerate(problems):
        print(
            f"\r  [ctrl {j + 1}/{len(problems)}] {problem['id']}...",
            end="", flush=True, file=sys.stderr,
        )
        messages.append({"role": "user", "content": problem["natural_language"]})

        t0 = time.perf_counter()
        response = client.messages.create(
            model=model,
            max_tokens=total_budget,
            system=CONTROL_SYSTEM_PROMPT,
            messages=messages,
        )
        elapsed = time.perf_counter() - t0

        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        messages.append({"role": "assistant", "content": text})

        completion = classify_completion(
            stop_reason=response.stop_reason,
            budget_hit=False,
            rounds_hit=False,
        )
        results.append({
            "raw_response": text,
            "extracted_answer": extract_answer(text),
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
            "stop_reason": response.stop_reason,
            "completion": completion,
            "truncated": completion != "end_turn",
            "total_budget": total_budget,
            "elapsed_s": round(elapsed, 3),
        })
        time.sleep(delay)

    return results


def run_treatment_session(
    client,
    model,
    problems,
    mcp_session,
    tools,
    delay,
    total_budget=5000,
    per_round_cap=5000,
    max_rounds=30,
):
    """Run all problems in a single treatment conversation."""
    cached_system = [
        {
            "type": "text",
            "text": TREATMENT_SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages = []
    results = []

    for j, problem in enumerate(problems):
        print(
            f"\r  [treat {j + 1}/{len(problems)}] {problem['id']}...",
            end="", flush=True, file=sys.stderr,
        )
        messages.append({"role": "user", "content": problem["natural_language"]})

        full_text = ""
        total_input_tokens = 0
        total_output_tokens = 0
        total_cache_creation_tokens = 0
        total_cache_read_tokens = 0
        tool_calls = 0
        tool_trace = []
        rounds = 0
        last_stop_reason = None
        budget_hit = False
        rounds_hit = False

        t0 = time.perf_counter()
        for round_i in range(max_rounds):
            remaining = total_budget - total_output_tokens
            if remaining <= 0:
                budget_hit = True
                break
            this_cap = max(1, min(per_round_cap, remaining))
            response = client.messages.create(
                model=model,
                max_tokens=this_cap,
                system=cached_system,
                messages=messages,
                tools=tools,
            )
            rounds += 1
            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens
            total_cache_creation_tokens += getattr(response.usage, "cache_creation_input_tokens", 0)
            total_cache_read_tokens += getattr(response.usage, "cache_read_input_tokens", 0)
            last_stop_reason = response.stop_reason

            tool_uses = []
            for block in response.content:
                if hasattr(block, "text"):
                    full_text += block.text
                if block.type == "tool_use":
                    tool_uses.append(block)

            if not tool_uses:
                # Append final assistant turn to shared history
                messages.append({"role": "assistant", "content": response.content})
                break

            tool_calls += len(tool_uses)
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in tool_uses:
                result = mcp_session.call_tool(block.name, block.input)
                tool_trace.append({
                    "tool": block.name,
                    "arguments": block.input,
                    "output": result,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })
            messages.append({"role": "user", "content": tool_results})

            if response.stop_reason == "end_turn":
                break
        else:
            # for-else: executed only if the loop didn't break. We exhausted
            # the round cap with the model still wanting tool use.
            if last_stop_reason == "tool_use":
                rounds_hit = True

        elapsed = time.perf_counter() - t0
        completion = classify_completion(
            stop_reason=last_stop_reason,
            budget_hit=budget_hit,
            rounds_hit=rounds_hit,
        )
        results.append({
            "raw_response": full_text,
            "extracted_answer": extract_answer(full_text),
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "cache_creation_tokens": total_cache_creation_tokens,
            "cache_read_tokens": total_cache_read_tokens,
            "stop_reason": last_stop_reason,
            "completion": completion,
            "truncated": completion != "end_turn",
            "total_budget": total_budget,
            "elapsed_s": round(elapsed, 3),
            "rounds": rounds,
            "tool_calls": tool_calls,
            "tool_trace": tool_trace,
        })
        time.sleep(delay)

    return results


# ── Main ─────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="A/B evaluation: LLM alone vs LLM + Wile algebra tools"
    )
    parser.add_argument(
        "--problems", required=True, help="Path to problems.json"
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).parent / "results.json"),
        help="Output file",
    )
    parser.add_argument(
        "--model", default="claude-sonnet-4-6", help="Claude model ID"
    )
    parser.add_argument("--wile", help="Path to wile binary")
    parser.add_argument(
        "--limit", type=int, help="Evaluate only the first N problems"
    )
    parser.add_argument(
        "--condition",
        choices=["control", "treatment", "both"],
        default="both",
        help="Which condition(s) to run",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds between API calls (rate limiting)",
    )
    parser.add_argument(
        "--total-budget",
        type=int,
        default=5000,
        help=(
            "Shared output-token budget for both control and treatment arms. "
            "Control uses this as max_tokens in a single call; treatment caps "
            "cumulative output across rounds. Default 5000 matches the "
            "calibrate_budget.py envelope (2x treatment p95)."
        ),
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=30,
        help=(
            "Maximum number of tool-calling rounds in treatment per problem. "
            "Default 30 (up from previous hard-coded 10). Round cap is a "
            "common failure mode for lattice-problem reasoning; raising it "
            "lets the model iterate helper functions to convergence."
        ),
    )
    parser.add_argument(
        "--session",
        action="store_true",
        help=(
            "Run all problems in a single conversation per condition. "
            "Prior exchanges remain in context, so errors can compound. "
            "Token cost is O(N²) in session length."
        ),
    )
    parser.add_argument(
        "--rescore",
        metavar="RESULTS_JSON",
        help="Re-score an existing results file and exit (no API calls).",
    )
    args = parser.parse_args()

    if args.rescore:
        with open(args.rescore) as f:
            results = json.load(f)
        for r in results:
            at = r.get("answer_type", "integer")
            gt = r["ground_truth"]
            prec = r.get("precision")
            if "control" in r:
                r["control_correct"] = answers_match(
                    r["control"]["extracted_answer"], gt, at, precision=prec
                )
            if "treatment" in r:
                r["treatment_correct"] = answers_match(
                    r["treatment"]["extracted_answer"], gt, at, precision=prec
                )
        with open(args.rescore, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Re-scored {args.rescore}", file=sys.stderr)
        condition = "both"
        if all("control" in r for r in results) and not any("treatment" in r for r in results):
            condition = "control"
        elif all("treatment" in r for r in results) and not any("control" in r for r in results):
            condition = "treatment"
        print_summary(results, condition)
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Set ANTHROPIC_API_KEY environment variable", file=sys.stderr)
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    mcp_session = None
    tools = None
    if args.condition in ("treatment", "both"):
        wile_binary = detect_wile(args.wile)
        print(f"Using Wile: {wile_binary}", file=sys.stderr)
        mcp_session = WileMCPSession(wile_binary)
        tools = mcp_tools_to_anthropic(mcp_session.list_tools())

    with open(args.problems) as f:
        problems = json.load(f)

    if args.limit:
        problems = problems[: args.limit]

    mode = "session" if args.session else "independent"
    print(
        f"Evaluating {len(problems)} problems, model={args.model}, "
        f"condition={args.condition}, mode={mode}",
        file=sys.stderr,
    )

    # Build skeleton result list keyed by problem id.
    # `precision` is carried through for decimal problems; None for others.
    results = [
        {
            "id": p["id"],
            "category": p["category"],
            "difficulty": p["difficulty"],
            "ground_truth": p["answer"],
            "answer_type": p.get("answer_type", "integer"),
            "precision": p.get("precision"),
        }
        for p in problems
    ]

    if args.session:
        if args.condition in ("control", "both"):
            ctrl_results = run_control_session(
                client, args.model, problems, args.delay,
                total_budget=args.total_budget,
            )
            for r, ctrl in zip(results, ctrl_results):
                r["control"] = ctrl
                r["control_correct"] = answers_match(
                    ctrl["extracted_answer"], r["ground_truth"],
                    r["answer_type"], precision=r.get("precision"),
                )
            print("", file=sys.stderr)

        if args.condition in ("treatment", "both"):
            treat_results = run_treatment_session(
                client, args.model, problems, mcp_session, tools, args.delay,
                total_budget=args.total_budget,
                max_rounds=args.max_rounds,
            )
            for r, treat in zip(results, treat_results):
                r["treatment"] = treat
                r["treatment_correct"] = answers_match(
                    treat["extracted_answer"], r["ground_truth"],
                    r["answer_type"], precision=r.get("precision"),
                )
            print("", file=sys.stderr)

    else:
        for j, (problem, result) in enumerate(zip(problems, results)):
            label = f"[{j + 1}/{len(problems)}] {problem['id']}"
            print(f"\r  {label}...", end="", flush=True, file=sys.stderr)

            if args.condition in ("control", "both"):
                ctrl = run_control(client, args.model, problem, max_tokens=args.total_budget)
                result["control"] = ctrl
                result["control_correct"] = answers_match(
                    ctrl["extracted_answer"], problem["answer"],
                    problem.get("answer_type", "integer"),
                    precision=problem.get("precision"),
                )
                time.sleep(args.delay)

            if args.condition in ("treatment", "both"):
                mcp_session.reset()
                treat = run_treatment(
                    client, args.model, problem, mcp_session, tools,
                    total_budget=args.total_budget,
                    max_rounds=args.max_rounds,
                )
                result["treatment"] = treat
                result["treatment_correct"] = answers_match(
                    treat["extracted_answer"], problem["answer"],
                    problem.get("answer_type", "integer"),
                    precision=problem.get("precision"),
                )
                time.sleep(args.delay)

        print("", file=sys.stderr)

    if mcp_session:
        mcp_session.close()

    # Re-score with current matching logic so stored correctness stays
    # consistent even if normalize_answer / answers_match evolve.
    for r in results:
        at = r.get("answer_type", "integer")
        gt = r["ground_truth"]
        prec = r.get("precision")
        if "control" in r:
            r["control_correct"] = answers_match(
                r["control"]["extracted_answer"], gt, at, precision=prec
            )
        if "treatment" in r:
            r["treatment_correct"] = answers_match(
                r["treatment"]["extracted_answer"], gt, at, precision=prec
            )

    # Write results
    output_path = Path(args.output)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Wrote results to {output_path}", file=sys.stderr)

    print_summary(results, args.condition)


if __name__ == "__main__":
    main()
