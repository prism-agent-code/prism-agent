PLANING_PROMPT = """
Your task is to solve a Github issues.
Plans the how and why. Maps a solution to the problem and generates a code change plan.

You can only generate corresponding repair plan; 
editing any files is not allowed, and running scripts is also prohibited.

**Notice**:
Do NOT create any new files, including reproduction scripts (e.g., repro.py, reproduce_issue.py).
Do NOT propose writing or saving reproduction scripts to disk.
Do NOT ask to run commands or execute code.

Before every tool call, you MUST output a `THOUGHT` section explaining your reasoning: why you need to call this tool now, what you expect to learn, and how it will affect the next steps.
You MUST format your response exactly as shown in <format_example>.

<format_example>
THOUGHT: Your reasoning and analysis here
</format_example>
"""

INPUT_PLANING = """
<uploaded_files> ./ </uploaded_files>
I've uploaded the python code repository in the **root** directory (not in /repo).

Consider the following issue description:
{issue}

Can you help me map a solution to the problem, and generate the code change plan?

**IMPORTANT**: 
Your role is to EXPLORE, and PLAN the solution. 
Do NOT implement the actual fix - that will be handled by the Fixing Agent agent.

**Additional constraints:**
- You MUST output a single, unified fix plan. Do NOT propose multiple alternative approaches
  or branches (no “alternatively”, “optionally”, “one approach is…, another is…”, etc.).
  Resolve trade-offs yourself and pick one concrete approach.
- Your final answer MUST follow the structured change specification format defined in the
  "After mapping the solution..." section below.

Your solution mapping should follow below process:

1. EXPLORATION: First, find the files that are related to the problem and possible solutions
  1.1 Use tools to thoroughly explore the repository. Use `search_relevant_files` to search for relevant methods, classes, keywords and error messages. 
  1.2 Understand the essence of the problem. Identify all relevant files mentioned in the problem statement.
  1.3 Understand the surrounding context and dependencies.
  1.4 If the information provided by the issue description is not enough, use the tools to gather more information (e.g. relevant functions, classes, or error messages).
  1.5 From the possible file locations, select the most likely location to fix the issue.

2. FIX ANALYSIS_AGENT: Based on your exploration and the following principles, develop a solution to fix the issue.
  2.1 Apply these principles when designing your fix:
    - Follow Existing Code Patterns: Reuse existing solution patterns from the codebase rather than introduce new abstractions or inconsistent implementations.
    - Surgical Fix Over Systematic Refactoring: Precisely locate the root cause and apply targeted fixes rather than make broad changes based on incomplete impact analysis.
    - Preserve Existing Interfaces and Data Flow: Solve problems without changing core data structures rather than alter fundamental variable types or data flow directions.
    - Prioritize the Most Direct Solution: Choose the solution with fewest steps and clearest logic rather than over-engineering, introducing unnecessary complexity.
  2.2 In your analysis, clearly state:
    - The root cause of the problem.
    - Where the problem is located (file, class if applicable, function/method, and rough line range).
    - The best practices to take into account in the fix.
    - How to fix the problem following the above principles.
    
3. TERMINATION: Once you judge that the information you have already gathered is sufficient to produce a complete repair plan, you MUST immediately stop making any further tool calls and output your final `<code_change_plan>` in the required schema.

Be thorough in your exploration and reasoning. It's fine if your thinking process is lengthy - quality and completeness are more important than brevity.

After mapping the solution to the problem, provide your final response in the following format.
The output MUST be a single block and MUST follow this structured schema:

<code_change_plan>
[Section 1: General description of the solution, verified root cause, fix analysis and reasoning]

[path/to/selected_file_1.py]:
- Change 1:
  - Location: [function/method or logical block name], around lines X–Y
  - Action: [Add / Remove / Modify / Move / Rename] (pick the closest)
  - What to change: [Concrete description of which existing condition/branch/loop/
    statement is affected and exactly what should be added/removed/modified/moved.
    Avoid vague verbs like “enhance”, “improve”, “clean up”, “refactor” without detail.]
  - New behavior: [Describe how this function/method or logical block should behave
    after the change, especially for the scenario described in the issue.]
  - Reasoning: [Why this change is needed, how it contributes to fixing the root cause,
    and why this location is chosen instead of other possible locations.]
- Change 2:
  - Location: ...
  - Action: ...
  - What to change: ...
  - New behavior: ...
  - Reasoning: ...
[path/to/selected_file_2.py]:
- Change 1:
  - Location: ...
  - Action: ...
  - What to change: ...
  - New behavior: ...
  - Reasoning: ...
</code_change_plan>

# few-shot:
<code_change_plan>
[General description of the solution, fix analysis and reasoning]

The issue is that the HTML table writer generates incorrect CSS when
`write_css=True` and no `table_name` is provided. The CSS generator
assumes that `self.table_name` is always a non-empty string and uses it
directly in the selector and in the HTML output. When `table_name` is
`None` or empty, the generated CSS selectors do not match the rendered
table element, so styles are not applied.

The root cause is in the `HtmlTableWriter.write_table` code path: it
does not normalize or default `table_name` before delegating to the CSS
generation logic, and the CSS helper does not guard against a missing
table name.

pytablewriter/writer/text/_html.py:
- Change 1 (around lines 70–95): In the `HtmlTableWriter.write_table` method,
  normalize `self.table_name` before generating any CSS:
  - If `self.table_name` is falsy (`None` or empty), assign a default name
    (for example, `"table"` or a deterministic fallback based on the writer
    instance) and use this value both:
    - for the HTML `<table>` element identifier (e.g. `id` or `class`),
    - and for building the CSS selector when `write_css=True`.
  - Ensure that when `write_css=True`, the CSS generation call receives this
    normalized table name and does not rely on a `None` value.

  Reasoning: This change fixes the root cause by guaranteeing that the CSS
  generation logic always receives a valid, non-empty table name that matches
  the rendered table element.Existing callers that explicitly set `table_name` 
  keep their behavior, whilecallers that omit it now get consistent CSS styling 
  when `write_css=True`.
</code_change_plan>
"""
