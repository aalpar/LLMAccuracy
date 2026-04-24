# Taxonomy of Optimization Problems

You're running a delivery company. You have 12 trucks, 200 packages, time
windows for each delivery, and fuel costs that depend on traffic. You want to
minimize total cost. Where do you even start?

The answer depends entirely on what kind of optimization problem you're looking
at — and "what kind" isn't about the domain (logistics, finance, ML), it's about
the *mathematical structure* of the choices you're making. That structure
determines which algorithms work, how hard the problem is, and whether you can
hope for an exact answer or need to settle for "good enough."

## What Makes Something an Optimization Problem?

Every optimization problem has exactly three ingredients:

1. **Decision variables** — the things you get to choose. Truck routes, portfolio
   weights, neural network parameters, antenna positions.

2. **Objective function** — the thing you're trying to minimize (or maximize).
   Cost, error, distance, profit. It takes your decision variables as input and
   returns a single number.

3. **Constraints** — the rules your choices must satisfy. Budget limits, physical
   laws, capacity bounds, "every package gets delivered exactly once."

Write it compactly: *minimize f(x) subject to x ∈ S*, where *x* is your
decision vector, *f* is the objective, and *S* is the **feasible region** — the
set of all *x* that satisfy every constraint.

That's it. Everything else is classification of what *f* and *S* look like.

## The Fundamental Split: What Are You Choosing?

Here's the question that cleaves the entire field in two: **are your decision
variables continuous or discrete?**

If you're choosing real numbers — portfolio weights, control signals, physical
coordinates — you're in **continuous (numeric) optimization**. The feasible
region is (typically) a connected chunk of ℝⁿ, and you can move through it in
small steps.

If you're choosing from a finite or countable set — which routes, which items to
pack, which edges to include, yes/no decisions — you're in **combinatorial
(discrete) optimization**. The feasible region is a scattered set of points with
no meaningful "small step" between them.

This isn't a cosmetic distinction. It determines your fundamental algorithmic
strategy:

- **Continuous**: you can compute gradients, follow slopes, make local
  improvements that inch toward the optimum. Calculus works.

- **Combinatorial**: there's no gradient. The neighbors of a solution aren't
  "nearby" in any smooth sense. You're searching a structured but
  non-differentiable landscape.

Mixed-integer problems straddle both worlds — some variables are continuous, some
are discrete. They're generally harder than either pure case.

```
                     Optimization
                          │
              ┌───────────┴───────────┐
              │                       │
         Continuous              Combinatorial
        (variables ∈ ℝ)        (variables discrete)
              │                       │
      ┌───────┴───────┐       ┌──────┴──────┐
      │               │       │             │
  Unconstrained  Constrained  Graph/       Integer
                       │      Network      Programming
                 ┌─────┴─────┐  Problems
                 │           │
             Linear      Nonlinear
           Programming   Programming
                          │
                    ┌─────┴─────┐
                    │           │
                 Convex     Non-convex
```

Let's walk each branch.

---

## Continuous Optimization

Your decision variables live in ℝⁿ. You're choosing a point in space.

### Unconstrained Optimization

The simplest setting: minimize *f(x)* with no restrictions on *x*. The feasible
region is all of ℝⁿ.

**Example**: training a neural network. The weights are real numbers, there are
millions of them, and you're minimizing a loss function with no hard bounds on
what the weights can be.

The workhorse strategy: **gradient descent** and its variants. Compute ∇f(x) —
the direction of steepest increase — and step the opposite way. If *f* is smooth
and well-behaved, you converge to a local minimum.

Key subcases:
- **Smooth and convex**: one minimum, gradient descent finds it. Life is good.
- **Smooth and non-convex**: many local minima, saddle points, plateaus. Gradient
  descent finds *a* local minimum, not necessarily *the* global one. This is the
  reality of deep learning.
- **Non-smooth**: *f* has kinks (think absolute value, ReLU). You need
  subgradient methods or proximal algorithms.

### Constrained Optimization

Now the feasible region *S* is a proper subset of ℝⁿ, carved out by
equalities and inequalities:

```
minimize  f(x)
subject to  gᵢ(x) ≤ 0    (inequality constraints)
            hⱼ(x) = 0    (equality constraints)
```

The nature of *f*, *g*, and *h* creates the taxonomy.

#### Linear Programming (LP)

Everything is linear: the objective is a linear function of *x*, and every
constraint is a linear inequality or equality.

```
minimize    cᵀx
subject to  Ax ≤ b
            x ≥ 0
```

**Example**: a factory produces chairs and tables using wood and labor. Each
product uses known amounts of each resource and yields known profit. Maximize
profit subject to resource limits.

Why this matters: LPs are **efficiently solvable**. The simplex method (1947)
walks along edges of the feasible polytope. Interior point methods (1984) cut
through the interior. Both find the *global* optimum — not an approximation, the
actual best answer. Problems with millions of variables are routine.

The feasible region of an LP is a **convex polytope** — a multi-dimensional
polygon. The optimum always sits at a vertex. This geometric fact is why the
simplex method works: it just hops between vertices, improving at each step.

#### Quadratic Programming (QP)

Linear constraints, but the objective is quadratic: *f(x) = ½ xᵀQx + cᵀx*.

**Example**: Markowitz portfolio optimization. Minimize portfolio variance
(quadratic in the weights) subject to a target return and weights summing to 1.

If *Q* is positive semidefinite, the problem is convex and efficiently solvable.
If not, it's NP-hard in general.

#### Nonlinear Programming (NLP)

The general case: *f* or the constraints (or both) are nonlinear. This is where
things get interesting — and where convexity becomes the critical dividing line.

**Convex NLP**: The objective is convex, the feasible region is a convex set.
Every local minimum is a global minimum. Interior point methods, cutting plane
methods, and other polynomial-time algorithms apply. Examples: semidefinite
programming (SDP), second-order cone programming (SOCP), geometric programming.
These form a hierarchy of increasing generality:

```
LP ⊂ QP ⊂ SOCP ⊂ SDP ⊂ Convex NLP
```

Each level adds expressiveness but remains tractable. This hierarchy is one of
the most useful structural facts in optimization — if you can reformulate your
problem to fit a tighter class, you get faster algorithms for free.

**Non-convex NLP**: Multiple local minima. No polynomial-time algorithm is known
for finding the global optimum in general. You're in the territory of local
search (gradient descent to a local minimum), global search heuristics
(simulated annealing, genetic algorithms), or branch-and-bound with convex
relaxations.

**Example**: protein folding — minimize free energy as a function of atomic
coordinates, subject to bond-length constraints. The energy landscape has an
astronomical number of local minima.

#### The Role of Convexity

This deserves emphasis because it's the single most important structural
property in continuous optimization.

A set *S* is convex if for any two points in *S*, the line segment between them
is also in *S*. A function *f* is convex if it "curves upward" — the function
value at any weighted average of two points is at most the weighted average of
the function values.

Why does this matter so much? Because of one theorem: **a local minimum of a
convex function over a convex set is a global minimum.** This means any
algorithm that finds a local minimum has found *the* answer. You never have to
worry about being trapped in a suboptimal valley.

This is such a powerful guarantee that a large fraction of optimization research
is devoted to: (a) recognizing when a problem is convex, (b) reformulating
problems into convex form, and (c) extending the frontier of what convex
optimization can express.

---

## Combinatorial Optimization

Now the decision variables are discrete. You're choosing from a finite (but
usually enormous) set of possibilities.

**The core difficulty**: you can't take gradients, and you can't make incremental
improvements along a smooth path. The landscape is a scatter of points, and
moving from one feasible solution to another might require changing many
variables simultaneously.

In principle, you could enumerate all feasible solutions and pick the best one.
In practice, the number of solutions is typically exponential — 2ⁿ subsets, n!
permutations — so brute force is hopeless for any non-trivial size.

### Graph and Network Problems

Many combinatorial problems are naturally expressed on graphs.

**Shortest Path**: given a weighted graph, find the minimum-cost path between two
nodes. Dijkstra's algorithm solves this in O(E + V log V). This is one of the
rare combinatorial problems that's efficiently solvable — the structure of
shortest paths (subpaths of shortest paths are also shortest paths) enables
dynamic programming.

**Minimum Spanning Tree**: connect all nodes at minimum total edge cost.
Kruskal's and Prim's algorithms solve this greedily in near-linear time. Again,
special structure (the matroid property) makes greediness optimal.

**Traveling Salesman Problem (TSP)**: visit every city exactly once and return
home, minimizing total distance. Unlike shortest path, TSP is **NP-hard**. No
known polynomial-time algorithm. The best exact solvers use branch-and-bound
with LP relaxations and can handle instances of ~100,000 cities, but the
computational cost grows steeply.

**Maximum Flow / Minimum Cut**: how much can flow through a network? Solvable in
polynomial time (Ford-Fulkerson, push-relabel). Duality with minimum cut is one
of the most elegant results in combinatorial optimization.

**Graph Coloring**: color vertices so no adjacent vertices share a color, using
the fewest colors. NP-hard. Even determining if a graph is 3-colorable is
NP-complete.

The pattern: some graph problems are in P (shortest path, MST, max-flow),
others are NP-hard (TSP, coloring, Hamiltonian path). The dividing line often
comes down to whether the problem has **optimal substructure** that algorithms
can exploit — whether solving small pieces correctly assembles into a global
solution.

### Integer Programming (IP) and Mixed-Integer Programming (MIP)

Take a linear program and add the constraint that some or all variables must be
integers.

```
minimize    cᵀx
subject to  Ax ≤ b
            x ≥ 0
            xᵢ ∈ ℤ for some (or all) i
```

**Example**: facility location. You have candidate sites for warehouses (binary:
build or don't) and continuous shipping quantities. Minimize total cost. The
binary decisions make this a MIP.

This looks like a small change from LP, but it's a qualitative leap in
difficulty. LP is polynomial; IP is NP-hard. The reason: the feasible region of
an LP is a smooth convex polytope, while the feasible region of an IP is a
scattered set of lattice points. The LP optimum sits at a vertex of the
polytope; the IP optimum might be nowhere near that vertex.

The standard approach: **LP relaxation + branch-and-bound**. Drop the integrality
constraint, solve the LP (fast), and use its solution as a bound. Then
systematically explore integer solutions, pruning branches that can't beat the
best known solution. Modern MIP solvers (Gurobi, CPLEX) layer on cutting planes,
heuristics, and presolve techniques to handle problems with millions of
variables and constraints — but worst-case complexity remains exponential.

### Packing, Covering, and Scheduling

These are families of problems with similar combinatorial structure:

**Knapsack**: given items with weights and values, choose a subset that maximizes
total value without exceeding a weight limit. NP-hard, but has a
pseudo-polynomial dynamic programming solution and excellent approximation
schemes (FPTAS).

**Set Cover**: given a universe of elements and a collection of subsets, find the
fewest subsets that cover every element. NP-hard. The greedy algorithm gives a
ln(n)-approximation — and that's essentially the best you can do in polynomial
time (unless P = NP).

**Job-Shop Scheduling**: assign jobs to machines over time, respecting precedence
and capacity constraints, minimizing makespan. NP-hard in general, though
special cases (single machine, two machines) are polynomial.

### Satisfiability and Constraint Satisfaction

At the discrete end: variables are boolean (or from small finite domains), and
you're looking for an assignment that satisfies a set of logical constraints.

**SAT**: given a boolean formula in conjunctive normal form, is there a
satisfying assignment? The canonical NP-complete problem. Modern SAT solvers
(CDCL-based) can handle instances with millions of variables for structured
problems, despite worst-case exponential complexity.

**MAX-SAT**: satisfy as many clauses as possible. An optimization version of SAT.
NP-hard to solve exactly, but admits constant-factor approximations.

---

## Cross-Cutting Concerns

Some properties cut across the continuous/discrete divide.

### Stochastic vs. Deterministic

In everything above, we assumed the data is known. In **stochastic
optimization**, some parameters are random variables — demand is uncertain, costs
fluctuate, measurements have noise.

This spawns its own taxonomy: stochastic programming (optimize expected value
over scenarios), robust optimization (optimize against worst-case uncertainty),
chance-constrained programming (constraints may be violated with bounded
probability), and online optimization (data arrives sequentially).

### Single-Objective vs. Multi-Objective

Sometimes you're minimizing cost *and* maximizing quality *and* minimizing
environmental impact. These objectives conflict. There's no single best answer —
instead, you're looking for the **Pareto frontier**: the set of solutions where
no objective can be improved without worsening another. Multi-objective
optimization produces this frontier rather than a single point.

### Static vs. Dynamic

**Static**: decide once, observe outcome. Most of classical optimization.

**Dynamic (optimal control)**: decisions unfold over time, and each decision
affects future state. Bellman's principle of optimality and dynamic programming
are the foundational tools. When the state space is continuous, this becomes
the Hamilton-Jacobi-Bellman equation or Pontryagin's maximum principle.

---

## The Hardness Landscape

Here's the practical takeaway — a rough map of tractability:

| Problem class              | Typical complexity     | What makes it tractable?              |
|----------------------------|------------------------|---------------------------------------|
| LP                         | Polynomial             | Convex polytope, vertex optimality    |
| Convex NLP (QP, SOCP, SDP)| Polynomial             | Local = global, interior point methods|
| Non-convex NLP             | NP-hard (in general)   | Special structure may help            |
| Shortest path, MST, flow  | Polynomial             | Optimal substructure, greedoids       |
| TSP, coloring, scheduling  | NP-hard                | Approximation algorithms, heuristics  |
| IP / MIP                   | NP-hard                | LP relaxation + branch-and-bound      |
| SAT                        | NP-complete            | CDCL solvers exploit structure        |

The single most important question when facing an optimization problem:
**does it have exploitable structure?** Convexity, optimal substructure,
matroid properties, total unimodularity — these structural features are what
separate tractable problems from intractable ones. And recognizing which
structure you have (or can impose through reformulation) is the core skill
of applied optimization.

## What Would Break Without This Taxonomy?

Why not just throw a general-purpose solver at every problem?

Because the wrong algorithm on the wrong structure either fails silently (finds
a terrible local minimum and reports it as optimal) or fails loudly (runs
until the heat death of the universe). Running gradient descent on a
combinatorial problem is nonsensical. Running branch-and-bound on an
unconstrained smooth problem is absurd overkill. Using a non-convex solver on a
convex problem throws away the guarantee that your answer is actually optimal.

The taxonomy isn't just academic filing — it's a decision procedure. Classify
your problem correctly, and you know which algorithms apply, what guarantees
you can expect, and what to do when the problem is too hard to solve exactly.
