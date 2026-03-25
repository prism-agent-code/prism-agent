BRANCH_STRATEGY_GUIDE = """
You are an AI assistant specialized in analyzing planning trajectories for bug-fix proposals.

I will provide:
- a GitHub issue (problem_statement)
- planning trajectories for this branch (trajectories)
- a branch_start_index for the CANONICAL trajectory

Your task is to analyze what has already been proposed in this branch and provide insights that help produce a materially different alternative solution.

You MUST return ONE JSON object in the required schema.
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
    Treat its facts, constraints, and high-level direction as your starting point.
  - Steps at branch_start_index and AFTER on the canonical trajectory will be discarded when branching.
- The “historical zone” consists of:
  - canonical[branch_start_index .. end], plus
  - all non-canonical trajectories.
  These show what kinds of plans have already been tried or proposed for this branch.

[Interpretation binding (STRICT)]
The preserved canonical context implicitly fixes the branch’s interpretation of the bug. You MUST NOT change it.
Specifically, treat the following as binding and non-negotiable for the NEXT attempt:
- failure surface: same failing tests / symptoms / repro conditions
- root-cause mechanism: the main causal story of why the failure happens (as established in the preserved context)
- behavioral contract: what the correct behavior is intended to be (as established in the preserved context)
- evidence anchors: the key observations/logs/code invariants used to justify the above
The NEXT attempt may refine details (edge cases, additional guards, clearer invariants), but must NOT replace the main causal story
or redefine the intended behavior contract. The alternative must stay “within the same interpretation” and only vary tactics.

[How to analyze]
1) Read the problem_statement and the preserved canonical context.
   - Treat explicit facts/constraints there as binding.
   - Extract and restate (for yourself) the branch-fixed items:
     failure surface, root-cause mechanism, behavioral contract, evidence anchors.
   - Keep the same failure surface focus (same failing tests / symptoms / repro conditions) as the preserved context.

2) Analyze the historical zone as prior attempts within this branch.
   - For EACH historical plan/trajectory, extract its main approach pattern:
     primary edit points, key change types, strategy style, technique used, assumptions/limitations, and what it did NOT touch.
   - Also look across all historical plans to understand what is repeatedly used as the default move.

3) Propose a different tactic for the NEXT attempt in this same branch (without changing the interpretation).
   - The alternative should avoid repeating the dominant technique(s) and should not modify the same function/section in the same way.
   - It may still touch the same files if necessary, but must change the tactic materially:
     responsibility split, enforcement point, refactor vs patch, test-first, diagnostics/guards, data-shape invariants, etc.
   - Prefer leveraging components/locations that were NOT primary levers in historical attempts but are plausibly relevant
     under the SAME fixed root-cause mechanism and contract.

[Output JSON schema (MANDATORY)]
Return ONE JSON object with EXACTLY these fields:

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

[Field meanings]
- per_plan_summaries:
  One entry per distinct historical plan/trajectory in the historical zone.

  For each entry:
  - plan_id:
    Short identifier for the plan/trajectory (use explicit IDs if present; otherwise stable labels).

  - approach_summary:
    summarizing THIS historical plan’s approach at a useful abstraction level.

  - modified_files:
    List of files/modules that THIS historical plan treats as PRIMARY levers.

  - key_changes:
    describing the main concrete change-types proposed in THIS plan:
    logic branches/checks, shape/matrix ops, API adjustments, config/flags, test edits/additions,
    error handling/logging, refactors.

  - strategy:
    The abstract core strategy of THIS plan (e.g., "local symmetry fix in operator helper",
    "caller-side special casing", "tighten validation to reject invalid inputs", "fallback/compat behavior").

  - specific_technique_from_history_solution:
    One distinctive technique/pattern THIS plan relied on that the new alternative should NOT reuse as its core move.

  - specific_files_or_functions:
    Specific files/functions/sections that THIS plan chose as main edit points; the new alternative should avoid
    modifying these in the SAME way/sequence (they may still be touched, but not with the same micro-plan).

  - assumptions_made_in_history_solution:
    Bullet-like statements (as a single string) capturing key assumptions/limitations behind THIS plan:
    root-cause hypothesis shape (within the fixed interpretation), invariants, compatibility trade-offs,
    what it assumes about inputs/outputs/shapes.

- component_not_touched_in_history_solution:
    Important components/modules/layers that, across all historical plans, seem relevant to the issue
    but were NOT used as main edit points.
    These are natural candidates for alternative fixes, especially when they are adjacent
    to the previously used locations.

- different_perspective:
  describing a concrete alternative direction for the NEXT attempt.
  It MUST:
  - stay consistent with the fixed failure surface, root-cause mechanism, and intended behavior contract from the preserved context,
  - clearly state what tactic changes (enforcement point, responsibility split, refactor vs patch, tests/diagnostics/guards),
  - explain how it avoids the dominant techniques from historical plans,
  - specify what tests/diagnostics you would add or adjust to lock the behavior.
  
[Few shot]
{{
  "per_plan_summaries": [
    {{
      "plan_id": "alt_1",
      "approach_summary": "Pins the bug on CONTINUE parsing: Card._split unescapes too early, so a doubled-quote split across chunks can collapse. Suggests delaying unescape and tweaking _strg for safer quote capture.",
      "modified_files": ["astropy/io/fits/card.py"],
      "key_changes": "Drop .replace(\"''\", \"'\") in Card._split; adjust _strg to treat \"''\" as content.",
      "strategy": "Delay unescape; harden quoted-string matching.",
      "specific_technique_from_history_solution": "Fixing _strg mainly by alternation reordering.",
      "specific_files_or_functions": ["Card._split", "_strg"],
      "assumptions_made_in_history_solution": "Early unescape is the cause; final unescape belongs in _parse_value; small regex tweak suffices."
    }}
  ],
  "component_not_touched_in_history_solution": "\"_words_group\" in astropy/io/fits/util.py, which could be made quote-token-aware so it never splits an escaped quote pair (''), preventing Card._format_long_image from creating CONTINUE boundaries that bisect the token.",
  "different_perspective": "Keep the same cause/contract. Replace alternation tweaks with a token-sequence _strg (?:''|[ -~])*? to be boundary-stable. Add a regression test that forces \"''\" to straddle CONTINUE boundaries and checks Card->str->Card preserves value."
}}

---Context---
#problem_statement:
{issue}

#Trajectories:
{planer_tj}

#branch_start_index:
{branch_index}
"""

strategy_branch_format = """I’ve reviewed the existing analysis, and here’s a summary of the current understanding:

{per_plan_summaries}

# New perspective
Now, based on the information above, explore a completely different approach. 
Instead of following the same strategy, consider tackling this from a "{different_perspective}" angle. 

You might want to investigate "{component_not_touched_in_history_solution}" as a potential area for your solution.
Remember, your goal is to create a plan that:
1. Solves the same problem but uses a fundamentally different approach
2. Avoids the techniques used in the history solution
3. Challenges the assumptions made in the history solution

Please analyze the problem again from this new perspective and develop your alternative solution.
"""
