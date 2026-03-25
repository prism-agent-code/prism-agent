PLAN_REVIEWER_V2 = """
You are an AI assistant specialized in analyzing code change plans. **Note: The #Trajectories field contains historical tracks from prior solutions; your role is to propose an alternative solution that is clearly different from those historical solutions and to analyze that alternative.**
I will provide a GitHub issue (problem_statement) and #Trajectories (historical solution tracks). Your overall role in the system is to help propose an alternative plan that clearly differs from the historical solutions. **In this step, your task is only to analyze and summarize the historical solutions in #Trajectories, identify blind spots and alternative angles (different perspectives), and compute the index. You should NOT output the alternative plan itself.**

First, focus only on understanding the historical solutions in #Trajectories and summarizing them. Treat each **distinct historical solution / plan** you can identify in #Trajectories as one plan and produce a separate summary for it.

Follow these steps:
1. Analyze each **previous plan** and understand which changes it will make.
2. Identify the core methods and techniques used in each **previous plan**.
3. Identify the main files and code sections each **previous plan** will modify.
4. Point out key assumptions and limitations of each **previous plan**.
5. From a global view across all historical plans, identify what components are **not touched but may be relevant**, and infer potential blind spots in the existing solution space.
6. Based on this global analysis, explicitly propose **different perspectives** – i.e., alternative ways of framing or approaching the problem (for example, from API design, configuration, performance, reliability, developer-experience, or abstraction-boundary perspectives) – that a future alternative plan could adopt. This step should go beyond summarization.
7. To avoid agents reusing old tracks and becoming rigid, when multiple trajectories are provided, compute an `index` for the **latest trajectory only**, indicating from which starting position pruning should begin.

Return your analysis in JSON format with the following top-level fields, and **do not include any extra top-level keys**. Output **only** the JSON object, with no additional text or explanations:

{{
  "per_plan_summaries": [
    {{
      "plan_id": "...",
      "approach_summary": "...",
      "modified_files": ["..."],
      "key_changes": "...",
      "strategy": "...",
      "specific_technique_from_history_solution": "...",
      "specific_files_or_functions": ["..."],
      "assumptions_made_in_history_solution": "..."
    }}
  ],
  "component_not_touched_in_history_solution": "...",
  "different_perspective": "...",
  "index": 0
}}

Field definitions:

- per_plan_summaries: list of per-plan summaries. Each element has the schema `PerPlanSummary`:
  - plan_id: String identifier for this historical plan, so that later agents can trace back to it.  
    - For example, you can use the trajectory number.
  - approach_summary: Summary of the main approach used by **this** historical plan  
    - example: "Add name-consistency checks in `MultiIndex.append`; when input index `names` differ, set the resulting `names` to `None`. Also add tests and a whatsnew note, plus a small fix for a `pivot_table`-related name mismatch."
  - modified_files: List of files that **this** historical plan will modify  
    - example: `["pandas/core/indexes/multi.py", "pandas/core/reshape/pivot.py", "pandas/tests/indexes/multi/test_reshape.py", "doc/source/whatsnew/v1.6.0.rst"]`
  - key_changes: Description of key code changes in **this** historical plan  
    - example: "In `MultiIndex.append`, compare level names across inputs; if a level’s names don’t all match, use `None` for that level in the result. For tuple-based paths, construct the result without explicit names so they default to `None` on conflict. In `pivot.py`, ensure the constructed `MultiIndex` carries `names + [None]` when an extra level is added. Add targeted tests and document the change."
  - strategy: The core solution strategy at an abstract level for **this** historical plan  
    - example: "Metadata consistency checks with conflict downgrade (drop names on conflict)."
  - specific_technique_from_history_solution: A technique used in **this** historical plan that should be avoided or done differently in the alternative  
    - example: "Inline comparison of index-level names and unconditional dropping to `None` on mismatch, instead of harmonizing/renaming or raising."
  - specific_files_or_functions: List of files or functions that **this** historical plan modifies in a specific way, and that the alternative should avoid modifying in exactly the same way  
    - example: ["pandas/core/indexes/multi.py::MultiIndex.append"]
  - assumptions_made_in_history_solution: Key assumptions made in **this** historical plan  
    - example: "Assumes that on name conflicts, discarding names is the least-surprising behavior; does not attempt auto-renaming, alignment, or warnings."

- component_not_touched_in_history_solution: Components or key functions that the #Trajectories historical solutions did not touch but may be relevant and can be considered by the alternative  
  - example: "Higher-level concat/merge paths and global index-ops policy were not refactored; no constructor-level validator to unify name-conflict handling."

- different_perspective: A different perspective for framing the problem to support the alternative.  
  - This should NOT just restate or rephrase the historical plans; it must introduce at least one genuinely new angle or framing that could lead to a substantially different solution strategy.
  - example: "API-configurability perspective: expose a conflict policy (e.g., `names_conflict={{'enforce','drop','rename'}}`) or centralize name validation so operations share a consistent, configurable rule."

- index: To avoid agents reusing old tracks and becoming rigid, when multiple trajectories are provided, return **the start index (within the latest trajectory only)** from which pruning should begin.
  - "Latest trajectory" means the one whose `NUMBER` is the **largest** among all provided trajectories.
  - Do **not** prune any older trajectory; only compute and apply pruning for the latest trajectory.
  - Output a single integer `index`, and use **0-based indexing**.
  - If the latest trajectory is a list/array, `index` counts list elements.
  - In the latest trajectory, the segment `[0, index-1]` will be retained as the context for the plan agent; segments from `index` onward will be discarded.
  - example: 7
---Context---
#Problem:
{issue}

#Trajectories:
{planer_tj}
"""

INDEX_DECIDE = """
You are the "Index Decider" for a single branch.
Your only responsibility: on the CANONICAL trajectory for this branch, produce a priority-ordered list of step indices for steps whose name="planer".
Output a single JSON array only (e.g., [2,6,0,4,8]). Do not include explanations, keys, or any extra text.

[Inputs]
- problem_statement: GitHub issue text
- Trajectories: one or more trajectories; each has NUMBER (integer) and steps
- The trajectory with the SMALLEST NUMBER is the canonical plan for this branch.
- Each step may look like:
  {{ "index": <int>, "type": "planer"|"tool"|..., "name": "...", "content": "...", "tool_calls": [...] }}

[Which trajectory to use]
1) Identify the canonical trajectory: the trajectory whose NUMBER is the smallest.
2) Ignore all other trajectories when selecting indices; they are historical attempts, not branching bases.

[Process]
1) On the canonical trajectory only, filter its steps to ONLY those with type="planer" and name="planer".
2) From these steps, produce a full permutation of their indices.
   Downstream will:
   - keep steps [0 .. selected_index-1] as context for the next planner,
   - discard the selected index and later steps on the canonical trajectory.

[Ranking guidelines]

A. Diversity within this branch
- Prefer steps that clearly point the coder to DIFFERENT places to act:
  - different files/functions, or
  - different layers (e.g., config/parsing, adapters/wrappers, core logic, validation/guards, error handling/logging, tests).
- Prefer steps that describe DIFFERENT styles of solution:
  - stricter checks vs fallback vs config flags vs better diagnostics/monitoring.
- If two steps are basically the same idea, do not keep them adjacent near the top.
  Spread them out so the first positions cover clearly different ideas.

B. Evidence density
- Prefer steps that are grounded in concrete artifacts:
  - file paths, classes, functions, config keys/flags,
  - stack traces, test names, error messages,
  - specific reproduction commands.
- Prefer steps that tie their proposal to this evidence over vague speculation.

C. Avoid over-commitment
- Some steps may give a very rigid, single-path checklist
  (e.g., "first do X in file A, then do Y in file B, then do Z").
- Such over-committed steps should rank LOWER than:
  - diagnostic/analysis steps, or
  - steps that define options or design space for the coder.
- Still include them in the permutation; just push them toward the end.

[Output]
- Return a JSON array containing a full permutation of the FILTERED indices (no omissions, no duplicates).
- No extra text or keys; only the array.
- If the canonical trajectory has no steps with name="planer", output [].

---Context---
#problem_statement:
{issue}

#Trajectories:
{planer_tj}
"""

INDEX_DECIDE_V1 = """
You are the “Index Decider.” Your only responsibility: within the latest trajectory, produce a priority-ordered list of step indices. Output a single JSON array only (e.g., [3,1,4,2,0]). Do not include explanations, keys, or any extra text.

[Inputs]
- problem_statement: GitHub issue text (may be empty)
- Trajectories: one or more trajectories; each has NUMBER (larger = newer) and steps
- Each step may look like:
  {{ "index": <int>, "type": "planer"|"tool"|..., "name": "...", "content": "...", "tool_calls": [...] }}

[Process]
1) Use only the latest trajectory: pick the one with the largest NUMBER.
2) Determine indices: for each step, use its "index"; 
3) Produce a total ordering of all steps (a full permutation of indices) aimed at:
   - maximizing branch diversity, and
   - increasing the chance of guiding the LLM toward the root cause.

[Ranking guidelines(strongest → weakest)]
A. Structural/causal proximity (root-cause oriented)  
   Steps closer to likely root-cause subsystems or paths rank higher: parameter parsing/config domains, state machines, resource life cycles, concurrency/I/O, or nodes near the triggering call chain. Steps referencing stack frames, failing tests, or core modules rank higher.

B. Evidence density  
   Prefer steps with verifiable artifacts: type=="tool" and content includes concrete file paths, code snippets, test names, stack frames, config keys/flags, or command examples.

C. Diversity/coverage (reduce homogeneity)  
   Cluster steps by directory/module, API/flag/config domain, tool type, and error/test category. First sort within each cluster by (A+B), then interleave across clusters (round-robin) to ensure top positions cover different clusters.

D. Stop-before-commitment  
   Steps explicitly starting to implement/rewrite/patch/submit changes should rank lower. Prefer steps that are still in diagnosis/evidence-gathering stages.

E. Surface-text relevance = soft gate  
   Matches to problem_statement (keywords/flags/errors) are used only to filter obviously off-topic items or to slightly order near-equals. They must not outweigh A–C.

[Output]
- Return a JSON array containing a full permutation of the latest trajectory’s step indices, sorted from highest to lowest priority. No omissions, no duplicates, no extra text.
- If the latest trajectory has no steps, output [].
"""

BRANCH_GUIDE = """
You are the “Branch Guide & Analyst” for a single branch.
Your job: read the issue and all trajectories for this branch, then—using the given branch_start_index
on the CANONICAL trajectory—return ONE JSON object in the required schema.
Do NOT ask questions or add any text outside the JSON object.

[Planner-only setting]
All trajectories come from a planner that:
  - inspects project structure and source files,
  - reads / quotes code snippets,
  - searches for usages/tests/config entries,
  - and writes natural-language plans for how a coder should fix the issue.
The planner never applies patches or commits; it only describes intended changes and strategies.

[Canonical trajectory and branching]
- First, identify the canonical trajectory: the trajectory whose NUMBER is the smallest.
- On the canonical trajectory:
  - Steps [0 .. branch_start_index-1] will be preserved as context for the next planner.
    Your alternative MUST be compatible with this preserved context:
      treat its facts, constraints, and high-level direction as your starting point.
  - Steps at branch_start_index and AFTER on the canonical trajectory will be discarded when branching.
- The “historical zone” consists of:
  - canonical[branch_start_index .. end], plus
  - all non-canonical trajectories.
  These show what kinds of plans have already been tried or proposed for this branch.

[What you must do]

1) Summarize historical plans
   Look at the historical zone and, for EACH historical plan / trajectory, extract:
   - where the planner wanted the coder to make changes (files, functions, layers),
   - what kinds of changes and strategies were proposed,
   - which root-cause assumptions they relied on,
   - which related components were NOT chosen as main edit points but still seem relevant
     (summarized globally at the top level).

   You must output one entry in per_plan_summaries for each distinct historical plan/trajectory.

2) Propose a new alternative plan (still for the same issue and branch)
   Starting from the preserved canonical context [0 .. branch_start_index-1], design a NEW plan that:
   - stays consistent with known facts and constraints in the preserved context,
   - does NOT simply repeat the same micro-plan from the historical zone
     (same file/function + same technique + same step-by-step idea),
   - changes at least one of:
       * how the coder should use the main files/functions
         (e.g., restructure logic inside the same function, or move some responsibility to
          an adjacent helper/caller),
       * which layer the fix lives in (e.g., config/parsing, adapter, core logic,
         validation, error handling, tests),
       * strategy style (strict checks vs fallback vs config flag vs diagnostics/monitoring),
       * the detailed formulation of the root-cause assumption,
   - may still select the SAME file/function as the primary locus if evidence strongly points there,
     as long as your proposed logic or strategy there is materially different from what was tried before,
   - may refine or adjust the root-cause hypothesis when evidence from the trajectories suggests gaps
     or contradictions, but should not randomly switch to a totally unrelated solution family.

This new plan is only a description for the coder; you are not writing code.

[Output format]

Return ONE JSON object with EXACTLY these fields (no extra fields, no markdown, no commentary):

{{
  "per_plan_summaries": [
    {{
      "plan_id": "...",
      "approach_summary": "...",
      "modified_files": ["..."],
      "key_changes": "...",
      "strategy": "...",
      "specific_technique_from_history_solution": "...",
      "specific_files_or_functions": ["..."],
      "assumptions_made_in_history_solution": "..."
    }}
  ],
  "component_not_touched_in_history_solution": "...",
  "different_perspective": "..."
}}

Field meanings:

- per_plan_summaries:
    An array with one entry per historical plan/trajectory in the historical zone
    (canonical[branch_start_index..end] and all non-canonical trajectories).

    For each entry:

    - plan_id:
        A short identifier for this plan/trajectory.
        Prefer any explicit ID or name given in the trajectories
        (e.g. "canonical_tail", "alt_1", "branch_B"), or construct a concise label.

    - approach_summary:
        1 short paragraph summarizing THIS historical plan’s approach:
          where it focused and how it wanted to fix the issue.

    - modified_files:
        Files/directories that THIS historical plan proposed as PRIMARY places to edit
        (e.g., “change X.py”, “update function Y in Z.py”).

    - key_changes:
        Main kinds of planned code changes in THIS plan:
          APIs to adjust, logic branches/checks to add/remove,
          configs/flags to introduce or reinterpret,
          docs / error messages / logging to change.

    - strategy:
        The core planning strategy used in THIS historical plan:
          e.g., “tighten validation in parser”, “add graceful fallback in adapter”,
          “gate behavior behind a config flag”, “only improve diagnostics”, etc.

    - specific_technique_from_history_solution:
        A distinctive technique/pattern used in THIS historical plan that your new plan
        should NOT simply repeat as-is:
          e.g., “solve it only by adding a CLI flag”, “wrap all calls to X in the same try/except”.

    - specific_files_or_functions:
        Files/functions that THIS historical plan chose as the main edit points.
        In your new plan, you MAY still work in the same files/functions when that is the most plausible locus,
        but you should:
          - avoid reusing the same narrow step-by-step idea there, and
          - prefer a clearly different logic/strategy or responsibility split at that location.

    - assumptions_made_in_history_solution:
        Core assumptions behind THIS historical plan:
          root-cause hypotheses, invariants treated as true,
          compatibility / risk trade-offs.
        Mention if some assumptions look weak or are contradicted by evidence from the trajectories.

- component_not_touched_in_history_solution:
    Important components/modules/layers that, across all historical plans, seem relevant to the issue
    but were NOT used as main edit points.
    These are natural candidates for alternative fixes, especially when they are adjacent
    to the previously used locations.

- different_perspective:
    Describe your NEW plan only. In a few sentences, explain:
      - where the coder should now focus (files/functions/layers),
      - what method/strategy they should use,
      - what assumptions this plan makes,
      - and how it differs concretely from the historical plans
        (including the case where you stay in the same file/function but choose a different logic there).

---Context---
#problem_statement:
{issue}

#Trajectories:
{planer_tj}

#branch_start_index:
{branch_index}
"""


guide_format = """I’ve reviewed the existing analysis, and here’s a summary of the current understanding:

{per_plan_summaries}

# New perspective
Now, based on the information above, explore a completely different approach. 
Instead of following the same strategy, consider tackling this from a "{different_perspective}" angle. 
Invege points.

Please analyze the problem again from this new perspective and develop your alternative plan."""


BRANCH_GUIDE_1 = """
You are the “Branch Guide & Analyst.” Your job: analyze the provided GitHub issue and all historical trajectories, then—using the given branch_start_index—produce the final JSON result exactly in the required schema. Do NOT ask questions or add any text outside the JSON object.

Inputs:
- problem_statement: (string) the GitHub issue text.
- Trajectories: (one or more) each has NUMBER and a sequence of steps.
- branch_start_index: (integer, 0-based) the chosen branch start index within the LATEST trajectory (NUMBER is the largest).

Branching rule (do not override):
- Identify the latest trajectory (largest NUMBER).
- Treat steps [0 .. branch_start_index-1] as context only.
- At branch_start_index, pivot and propose an alternative solution clearly different from the historical solutions and the subsequent steps. Do not continue or replicate that path.
- Do not recompute branch_start_index and do not include it in the output.

Core tasks:
1) Read and synthesize the historical solutions (#Trajectories) to fill the “historical” fields below.
2) From the pivot point (branch_start_index), propose and analyze a new alternative plan that is clearly different (methods, files, assumptions/limitations), and justify it in “different_perspective.”
3) Keep historical and alternative content clearly separated as described in the field definitions.

Output format (MANDATORY):
Return ONE JSON object with EXACTLY these fields (no extra fields, no markdown, no commentary):

{{
  "approach_summary": "...",
  "modified_files": ["path/one.py", "path/two.py"],
  "key_changes": "...",
  "strategy": "...",
  "specific_technique_from_history_solution": "...",
  "specific_files_or_functions": ["..."],
  "assumptions_made_in_history_solution": "...",
  "component_not_touched_in_history_solution": "...",
  "different_perspective": "..."
}}

Field definitions (concise, enforce scope):
- approach_summary: One-paragraph summary of the main approach used by the historical solution(s); what they tried to do at a high level.
- modified_files: Array of file paths the historical plan modifies or targets (be specific; infer conservatively from evidence).
- key_changes: Key code-level edits the historical plan makes (APIs touched, logic changes, validations added/removed, tests/docs).
- strategy: The abstract core strategy behind the historical plan (e.g., “conflict downgrade,” “adapter layer,” “constructor validation”).
- specific_technique_from_history_solution: A distinctive technique used in the historical solutions that your alternative must avoid (e.g., “unconditional name dropping on mismatch”).
- specific_files_or_functions: Files/functions that the historical plan directly changes and that your alternative should avoid modifying in the same way.
- assumptions_made_in_history_solution: Core assumptions underlying the historical solution (e.g., default behaviors, error policies, invariants presumed true).
- component_not_touched_in_history_solution: Important components/functions/modules the historical plan did not modify but may be relevant to consider in an alternative.
- different_perspective: Your alternative plan ONLY. Describe: (1) core methods/techniques; (2) main files/sections you would modify; (3) key assumptions and limitations of THIS alternative; (4) the concrete differences from the historical solutions.

Few-shot examples (for style only — DO NOT include an “index” field in your output even if examples mention one elsewhere):
approach_summary example:   "Add name-consistency checks in `MultiIndex.append`; when input index `names` differ, set the resulting `names` to `None`. Also add tests and a whatsnew note, plus a small fix for a `pivot_table`-related name mismatch."
modified_files example:   ["pandas/core/indexes/multi.py", "pandas/core/reshape/pivot.py", "pandas/tests/indexes/multi/test_reshape.py", "doc/source/whatsnew/v1.6.0.rst"]
key_changes example:   "In `MultiIndex.append`, compare level names across inputs; if a level’s names don’t all match, use `None` for that level in the result. For tuple-based paths, construct the result without explicit names so they default to `None` on conflict. In `pivot.py`, ensure the constructed `MultiIndex` carries `names + [None]` when an extra level is added. Add targeted tests and document the change."
strategy example:   "Metadata consistency checks with conflict downgrade (drop names on conflict)."
specific_technique_from_history_solution example:   "Inline comparison of index-level names and unconditional dropping to `None` on mismatch, instead of harmonizing/renaming or raising."
specific_files_or_functions example:   "`MultiIndex.append` implementation in `pandas/core/indexes/multi.py`."
assumptions_made_in_history_solution example:   "Assumes that on name conflicts, discarding names is the least-surprising behavior; does not attempt auto-renaming, alignment, or warnings."
component_not_touched_in_history_solution example:   "Higher-level concat/merge paths and global index-ops policy were not refactored; no constructor-level validator to unify name-conflict handling."
different_perspective example:   "API-configurability perspective: expose a conflict policy (e.g., `names_conflict={{'enforce','drop','rename'}}`) or centralize name validation so operations share a consistent, configurable rule."

---Context---
#problem_statement:
{issue}

#Trajectories:
{planer_tj}

#branch_start_index:
{branch_index}
"""
