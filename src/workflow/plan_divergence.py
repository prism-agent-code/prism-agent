import os
from collections import defaultdict
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langchain.agents import create_agent
from langgraph.types import Command
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from typing_extensions import TypedDict

from src.agent.constant import SUB_PLAN_NUM
from src.agent.llm import llm, mapper_llm, reviewer_llm

from src.agent.prompt.integration_agent import INTEGRATION_PLANER
from src.agent.prompt.plan_agent import PLANING_PROMPT, INPUT_PLANING
from src.agent.prompt.planer_reviewer import INDEX_DECIDE, BRANCH_GUIDE, guide_format
from src.agent.root_cause_prompt.strategy_branch import BRANCH_STRATEGY_GUIDE, strategy_branch_format
from src.agent.state import SubState
from src.agent.tool_set.context_tools import search_relevant_files
from src.agent.tool_set.edit_tool import str_replace_editor
from src.agent.tool_set.sepl_tools import view_directory, view_file_content, think, view_file_structure, \
    search_files_by_keywords, run_shell_cmd
from src.agent.tool_set.utils import format_tjs, format_plans, fromat_trace, Top_branch_guide, summarize_content, \
    format_plan_summery


def save_trj(dir_path: str, file_name: str, content: str):
    file_path = os.path.join(dir_path, file_name)
    os.makedirs(dir_path, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)


class Indexes_list(TypedDict):
    indexes: list[int]


def sub_reviewer(state: SubState):
    if len(state["trajectory"]) >= SUB_PLAN_NUM:
        return Command(
            update={
                "guide": ""
            },
            goto='integration_planer'
        )
    planer_state = {
        "planer_tj": format_tjs(state["trajectory"]),
        "issue": state["issue"],
    }
    indexes = None
    system_message = SystemMessage(content="Convert user content into JSON format")
    req = 0
    while not indexes:
        if req > 3:
            indexes = [0]
            break
        result_index = reviewer_llm.invoke([
            HumanMessage(INDEX_DECIDE.format_map(defaultdict(str, planer_state)))])
        indexes = llm.with_structured_output(Indexes_list).invoke([system_message, HumanMessage(result_index.content)])[
            "indexes"]
        req += 1
    max_n = len(indexes) - 1
    temp_list = []
    for i, index in enumerate(indexes):
        temp_list.append((max_n - i) * 0.7 + (index * 0.5) * 0.3)
    sorted_indices = sorted(range(len(temp_list)), key=temp_list.__getitem__, reverse=True)
    final_indexes = [indexes[i] for i in sorted_indices]
    branch_index = final_indexes[0]
    while not isinstance(state["trajectory"][0][branch_index], AIMessage):
        branch_index -= 1
    branch_state = {
        "planer_tj": format_tjs(state["trajectory"]),
        "issue": state["issue"],
        "branch_index": branch_index,
    }
    result_guide = None
    req = 0
    while not (result_guide and result_guide.content):
        if req >= 3:
            break
        result_guide = reviewer_llm.invoke([HumanMessage(BRANCH_STRATEGY_GUIDE.format_map(defaultdict(str, branch_state)))])
        req += 1
    response = llm.with_structured_output(Top_branch_guide).invoke([system_message, HumanMessage(result_guide.content)])
    guide_state = {
        "per_plan_summaries": format_plan_summery(response['per_plan_summaries']),
        "component_not_touched_in_history_solution": response['component_not_touched_in_history_solution'],
        "different_perspective": response['different_perspective'],
    }
    return Command(
        update={
            "guide": strategy_branch_format.format_map(defaultdict(str, guide_state)),
            "index": branch_index
        },
        goto="sub_planer"
    )


plan_tools = [view_directory, view_file_structure, view_file_content,
                         search_relevant_files,
                         search_files_by_keywords]

plan_agent = create_agent(
    mapper_llm,
    tools=plan_tools,
    system_prompt=PLANING_PROMPT,
)


def run_agent(input_message, run_config, repo_path, tj_path, agent):
    result = None
    for latest_state in agent.stream(
            {"messages": input_message},
            config=run_config,
            stream_mode="values",
    ):
        result = latest_state
        save_trj(repo_path, tj_path, fromat_trace(result["messages"]))
    return result


notice_plan = ("Please continue your work. If you believe you have obtained enough information to complete your task, "
               "please output exactly one unified fix plan, wrapped with <code_change_plan> and </code_change_plan>.")


def sub_planer(state: SubState):
    solution_state = {
        "issue": state["issue"],
    }
    message = HumanMessage(INPUT_PLANING.format_map(defaultdict(str, solution_state)))
    message.name = "user"
    solution_mapper_trajectory = state["trajectory"][0][:state["index"]]
    input_message = [message] + solution_mapper_trajectory
    suggestion_message = HumanMessage(state["guide"])
    suggestion_message.name = "user"
    input_message += [suggestion_message]
    plan_config = {"recursion_limit": 200}
    notice_plan_message = HumanMessage(content=notice_plan)
    notice_plan_message.name = "user"
    result = run_agent(input_message, plan_config,
                       f'tjs/{state['repo']}/{state['test_date']}/{state["instance_id"]}/top_plan_{str(state['NUMBER'])}',
                       "sub_plan_" + str(len(state["trajectory"])) + ".json", plan_agent)
    final_content = result["messages"][-1].content
    requeries = 0
    while "<code_change_plan>" not in final_content or "</code_change_plan>" not in final_content:
        result = run_agent(result['messages'][:-1] + [notice_plan_message], plan_config,
                           f'tjs/{state['repo']}/{state['test_date']}/{state["instance_id"]}/top_plan_{str(state['NUMBER'])}',
                           "sub_plan_" + str(len(state["trajectory"])) + ".json", plan_agent)
        final_content = result["messages"][-1].content
        requeries += 1
        if requeries >= 3:
            break
    new_messages = result["messages"]
    for msg in new_messages:
        if isinstance(msg, AIMessage):
            msg.name = "planer"
    tool_use_tj = new_messages[state["index"] + 2:]
    save_trj(f'tjs/{state['repo']}/{state['test_date']}/{state["instance_id"]}/top_plan_{str(state['NUMBER'])}',
             "sub_plan_" + str(len(state["trajectory"])) + ".json",
             fromat_trace(new_messages))
    solution_mapper_trajectory += tool_use_tj
    state["trajectory"].append(solution_mapper_trajectory)
    return Command(
        update={
            "trajectory": state["trajectory"]
        },
        goto="sub_reviewer",
    )


def integration_planer(state: SubState):
    integration_state = {
        'issue': state["issue"],
        'traces': format_tjs(state["trajectory"]),
        'plans': format_plans([t[-1].content for t in state["trajectory"]])
    }
    final_plan = None
    re_q = 0
    while not (final_plan and final_plan.content):
        if re_q >= 3:
            break
        final_plan = reviewer_llm.invoke([
            HumanMessage(INTEGRATION_PLANER.format_map(defaultdict(str, integration_state)))])
        re_q += 1
    save_trj(f'tjs/{state['repo']}/{state['test_date']}/{state["instance_id"]}/top_plan_{str(state['NUMBER'])}',
             "sub_final_plan.txt",
             final_plan.content)
    return Command(
        update={
            'result': final_plan.content,
        },
        goto=END
    )


sub_builder = StateGraph(SubState)
sub_builder.add_edge(START, "sub_reviewer")
sub_builder.add_node(
    "sub_reviewer",
    sub_reviewer
)
sub_builder.add_node(
    "sub_planer",
    sub_planer
)
sub_builder.add_node(
    "integration_planer",
    integration_planer
)

sub_graph = sub_builder.compile()