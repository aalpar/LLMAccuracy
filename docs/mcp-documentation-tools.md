# MCP Documentation Tools for LLM Algebra Accuracy

## Problem

When running the algebra accuracy benchmark with Wile MCP tools (treatment condition), Sonnet 4.6 achieves ~95% accuracy overall — except for **powerset lattice**, where treatment is *worse* than control (80% vs 90% at hard, 80% vs 100% at extra-hard). Analysis of the tool traces reveals the LLM wastes rounds on failed discovery and never reaches the correct computation.

## Root Cause Analysis

Three distinct failure modes observed in powerset lattice treatment traces:

### 1. Algebra library not loaded
The LLM calls `doc("(wile algebra)")` and gets "Library (wile algebra): not loaded". Functions like `lattice-join`, `lattice-meet`, `powerset-lattice` are invisible to `doc` and `apropos` because they only search loaded bindings.

### 2. Wrong import conventions
When falling back to manual set operations, the LLM tries:
- `(import (srfi srfi-1))` — Guile/Chicken convention, fails in Wile
- `filter`, `fold-right`, `sort`, `list-sort` without any import
- `symbol<?` — doesn't exist

The correct import is `(import (srfi 1))` (R7RS naming), but the LLM has no way to discover this. The `apropos` and `doc` tools only search loaded bindings.

### 3. Round limit exhaustion
After 5-7 rounds of failed discovery and broken implementations, the LLM hits the 10-round cap before computing the answer.

## Key Insight

The LLM already knows Scheme — it writes correct `cond`, `let`, `lambda`, `member`. General R7RS documentation wouldn't help. What it lacks is **Wile-specific knowledge**:
- Import names: `(srfi 1)` not `(srfi srfi-1)`
- Which libraries exist and what they export
- That `filter`/`fold-right` require `(srfi 1)`
- That `lattice-join`/`powerset-lattice` require `(wile algebra)`
- Function signatures for algebra primitives

## Proposed Solutions

### Option A: MCP `library-doc` Tool (Recommended)

Add a tool to the Wile MCP server that returns documentation for available (not necessarily loaded) libraries.

**Why this approach:**
- Fits the existing `evaluate.py` tool-use loop with zero client changes
- Mirrors the `doc`/`apropos` pattern the LLM already follows
- The LLM decides when to look up docs (only when needed)

**Behavior:**
- `library-doc("(wile algebra)")` → exports, signatures, one-line descriptions, usage examples
- `library-doc("(srfi 1)")` → same for SRFI-1
- `library-doc()` with no argument → catalog of all available libraries with import names

### Option B: MCP Resources

Expose documentation as MCP resources:
- `wile://docs/libraries` — catalog with import names
- `wile://docs/wile-algebra` — exports and examples for `(wile algebra)`
- `wile://docs/srfi-1` — same for `(srfi 1)`

**Drawback:** The current `evaluate.py` only uses `tools/list` and `tools/call`. It would need modification to call `resources/list` and `resources/read` at session start, then inject docs into the system prompt.

### Option C: Pre-import Libraries in MCP Session

Pre-load `(wile algebra)` and `(srfi 1)` in the MCP eval session so common building blocks are always available.

**Drawback:** Changes the default session state. The existing `doc` and `apropos` tools would then find algebra symbols, but still return `#!void (runtime)` for undocumented functions. Doesn't solve the documentation quality problem.

## Supporting Data

### Sonnet 4.6 Control Accuracy Gradient (2026-04-08)

| Category | easy | medium | hard | extra-hard | super-hard | ultra-hard |
|---|---|---|---|---|---|---|
| fixpoint | 100% | 100% | 100% | 100% | 100% | 100% |
| modular_arithmetic | 100% | 50% | 20% | 0% | 0% | 0% |
| monoid_fold | 100% | 100% | 100% | 100% | 20% | 0% |
| monoid_power | 70% | 0% | 0% | 0% | 0% | 0% |
| powerset_lattice | 100% | 100% | 90% | 100% | 0% | 0% |
| rational_field | 100% | 50% | 0% | 0% | 0% | 0% |
| tropical_semiring | 100% | 100% | 90% | 0% | 80% | 0% |

### Treatment vs Control at Break Zones

| Category | Difficulty | Control | Treatment | Delta |
|---|---|---|---|---|
| modular_arithmetic | medium | 50% | 100% | +50% |
| modular_arithmetic | hard | 20% | 100% | +80% |
| modular_arithmetic | extra-hard | 0% | 100% | +100% |
| monoid_power | easy | 70% | 100% | +30% |
| monoid_power | medium | 0% | 100% | +100% |
| rational_field | medium | 50% | 100% | +50% |
| rational_field | hard | 0% | 100% | +100% |
| **powerset_lattice** | **hard** | **90%** | **80%** | **-10%** |
| **powerset_lattice** | **extra-hard** | **100%** | **80%** | **-20%** |
| powerset_lattice | super-hard | 0% | 40% | +40% |

### Cost Comparison (125 targeted problems)

|  | Control | Treatment | Ratio |
|---|---|---|---|
| Input tokens | 40,666 | 1,378,919 | 33.9x |
| Output tokens | 108,014 | 171,697 | 1.6x |
| API cost | $1.74 | $6.71 | 3.9x |
| Correct answers | 58/125 | 119/125 | |
| Cost/correct | $0.030 | $0.056 | |

### Available Wile Libraries (relevant subset)

```
(srfi 1)              — SRFI-1 list library (filter, fold, fold-right, etc.)
(wile algebra)        — Algebraic structures (rings, fields, semirings, lattices)
(wile algebra lattice) — Lattice operations
(wile algebra ring)   — Ring operations
(wile algebra semiring) — Semiring operations
(wile all)            — All Wile extensions combined
```

## Files

- `algebra-accuracy/sonnet_control_gradient.json` — 300-problem control results across all difficulties
- `algebra-accuracy/sonnet_treatment_gradient.json` — 125-problem treatment results at break zones
- `algebra-accuracy/gradient_problems.json` — generated problem set (seed 42)
- `algebra-accuracy/generate.py` — problem generator
- `algebra-accuracy/evaluate.py` — A/B evaluation harness
- `algebra-accuracy/validate.py` — independent Python ground-truth validator
