import argparse
import asyncio
import os
from collections import defaultdict
import uuid

import dotenv
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langchain.agents import create_agent
from langgraph.types import Command, Send
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage, AnyMessage
from typing_extensions import TypedDict
from src.agent.constant import PLAN_NUM
from src.agent.llm import llm, mapper_llm, reviewer_llm, coder_llm
from src.agent import runtime_config
from src.agent.prompt.coder import CODER_SYSTEM, CODER_INPUT
from src.agent.prompt.plan_agent import PLANING_PROMPT, INPUT_PLANING
from src.agent.prompt.top_branch import TOP_PLAN_GUIDE, top_guide_format
from src.agent.root_cause_prompt.root_branch import TOP_BRANCH_WORLDVIEW_GUIDE, top_guide_worldview_format
from src.agent.tool_set.context_tools import search_relevant_files
from src.agent.tool_set.utils import fromat_trace, Top_branch_guide, format_tjs, format_plans, summarize_content, \
    format_plan_summery, TopWorldviewBranchGuide, format_worldview_plan_summery

from src.agent.state import CustomState
from src.agent.tool_set.edit_tool import str_replace_editor
from src.agent.tool_set.sepl_tools import view_file_content, view_directory, run_shell_cmd, think, \
    extract_git_diff_swe_rex, search_files_by_keywords, view_file_structure, submit
from src.workflow.plan_divergence import sub_graph

rc = runtime_config.RuntimeConfig()

plan_tools = [view_directory, view_file_structure, view_file_content,
                         search_relevant_files,
                         search_files_by_keywords]
coder_tools = [view_directory, view_file_structure, search_relevant_files, str_replace_editor, run_shell_cmd, submit]
dotenv.load_dotenv(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        ".env",
    )
)


def save_trj(dir_path: str, file_name: str, content: str):
    file_path = os.path.join(dir_path, file_name)
    os.makedirs(dir_path, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)


def input_handler_node(state: CustomState):
    """in issue solving, input handler will take input of
    1.swe-bench id,
    2.issue link and set up the env accordingly"""
    rc.load_from_swe_rex_docker_instance(state["instance_id"], state["base_commit"])
    rc.proj_name = state["instance_id"]
    print(rc.look_status_all_config())
    issue_description = rc.issue_desc
    return Command(
        update={
            "messages": [HumanMessage(content=issue_description)],
            "issue": issue_description,
            "last_agent": "input_handler",
            "problem_decoder_result": "",
            "solution_mapper_result": "",
            "problem_solver_result": "",
            "repro_tester_result": "",
            "index": -1
        },
        goto="planer",
    )


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
        save_trj(repo_path, tj_path,
                 fromat_trace(result["messages"])
                 )
    return result


notice_plan = ("Please continue your work. If you believe you have obtained enough information to complete your task, "
               "please output exactly one unified fix plan, wrapped with <code_change_plan> and </code_change_plan>.")


def planer(state: CustomState):
    solution_state = {
        "issue": state["issue"],
    }
    message = HumanMessage(INPUT_PLANING.format_map(defaultdict(str, solution_state)))
    message.name = "user"
    input_message = [message]
    if state["guide"] != "":
        suggestion_message = HumanMessage(state["guide"])
        suggestion_message.name = "user"
        input_message += [suggestion_message]
    plan_config = {"recursion_limit": 200}
    result = None
    # todo 加一个<code_change_plan>匹配 如果没有匹配应该重传
    notice_plan_message = HumanMessage(content=notice_plan)
    notice_plan_message.name = "user"
    # try:
    result = run_agent(input_message, plan_config,
                       f'tjs/{state['repo']}/{state['test_date']}/{state["instance_id"]}',
                       "top_plan_" + str(len(state['tjs_list'])) + ".json", plan_agent)
    final_content = result["messages"][-1].content
    requeries = 0
    while "<code_change_plan>" not in final_content or "</code_change_plan>" not in final_content:
        result = run_agent(result['messages'][:-1] + [notice_plan_message], plan_config,
                           f'tjs/{state['repo']}/{state['test_date']}/{state["instance_id"]}',
                           "top_plan_" + str(len(state['tjs_list'])) + ".json", plan_agent)
        final_content = result["messages"][-1].content
        requeries += 1
        if requeries >= 3:
            break
    new_messages = result["messages"]
    for msg in new_messages:
        if isinstance(msg, AIMessage):
            msg.name = "planer"
    tool_use_tj = new_messages[state["index"] + 2:]
    save_trj(f'tjs/{state['repo']}/{state['test_date']}/{state["instance_id"]}',
             "top_plan_" + str(len(state['tjs_list'])) + ".json", fromat_trace(new_messages))
    new_tjs_list = state["tjs_list"] + [tool_use_tj]
    return Command(
        update={
            "solution_mapper_result": result["messages"][-1].content,
            "solution_mapper_tj": tool_use_tj,
            "tjs_list": new_tjs_list,
        },
        goto="start_branch",
    )
def start_branch(state: CustomState):
    if len(state["tjs_list"]) >= PLAN_NUM:
        return Command(
            update={
                "guide": ""
            },
            goto='dispatcher'
            # goto=END
        )
    system_message = SystemMessage(content="Convert user content into JSON format")
    branch_state = {
        "planer_tj": format_tjs(state["tjs_list"]),
        "issue": state["issue"],
    }
    result_guide = None
    req = 0
    while not (result_guide and result_guide.content):
        if req >= 3:
            break
        result_guide = reviewer_llm.invoke(
            [HumanMessage(TOP_BRANCH_WORLDVIEW_GUIDE.format_map(defaultdict(str, branch_state)))])
        req += 1
    response = llm.with_structured_output(TopWorldviewBranchGuide).invoke(
        [system_message, HumanMessage(result_guide.content)])
    guide_state = {
        "per_plan_summaries": format_worldview_plan_summery(response['per_plan_summaries']),
        "different_worldview": response["different_worldview"]
    }
    return Command(
        update={
            "guide": top_guide_worldview_format.format_map(defaultdict(str, guide_state)),
            "solution_mapper_tj": [],
            "index": 0
        },
        goto="planer"
    )


def dispatcher(state: CustomState):
    sends = []
    for idx, t in enumerate(state["tjs_list"]):
        sub_state = {
            'issue': state['issue'],
            'temp_tj': [t],
            'NUMBER': idx,
            'instance_id': state['instance_id'],
            'repo': state['repo'],
            'test_date': state['test_date']
        }
        sends.append(Send("sub_worker", sub_state))
    return Command(
        goto=sends,
        update={"final_plans": []},
    )


def sub_worker(state):
    sub_input = {
        "index": 0,
        "issue": state['issue'],
        "guide": "",
        "trajectory": state["temp_tj"],
        "result": "",
        "NUMBER": state['NUMBER'],
        "instance_id": state['instance_id'],
        'repo': state['repo'],
        'test_date': state['test_date']
    }
    sub_result = sub_graph.invoke(sub_input)
    return Command(
        update={
            "final_plans": [sub_result["result"]]
        },
        goto="plan_select"
    )


class select_idx(TypedDict):
    NUMBER: int


def plan_select(state: CustomState):
    idx = len(state['patch_pool'])
    if idx >= PLAN_NUM:
        return Command(
            goto=END
        )
    return Command(
        update={
            'final_plan': state["final_plans"][idx]
        },
        goto='coder'
    )


coder_agent = create_agent(
    coder_llm,
    tools=coder_tools,
    system_prompt=CODER_SYSTEM,
)


def run_coder(input_message, run_config, repo_path, tj_path, agent):
    result = None
    for latest_state in agent.stream(
            {"messages": input_message},
            config=run_config,
            stream_mode="values",
    ):
        result = latest_state
        messages = result["messages"]
        save_trj(repo_path, tj_path, fromat_trace(messages))

        if len(messages) > 350:  # 超过最大迭代次数
            raise GraphRecursionError

    return result


notice_user = ("Please continue your work. If you believe you have finished, please submit your work using the submit "
               "tool.")

def coder(state: CustomState):
    idx = len(state['patch_pool'])
    coder_state = {
        'ISSUE': state["issue"],
        'final_plan': state['final_plan'],
        'test_instruction': state["test_instruction"]
    }
    input_message = [HumanMessage(CODER_INPUT.format_map(defaultdict(str, coder_state)))]
    notice_message = HumanMessage(content=notice_user, name="user")
    coder_result: dict[str, list[AnyMessage]] = {"messages": input_message + [notice_message]}
    code_config = {"recursion_limit": 350, }
    repo_path = f'tjs/{state['repo']}/{state['test_date']}/{state["instance_id"]}/top_plan_{idx}'
    req = 0
    rc.have_submit = False
    while not rc.have_submit and req <= 3:
        coder_result = run_agent(coder_result["messages"][:-1] + ([notice_message] if req != 0 else []),
                                 code_config,
                                 repo_path,
                                 "coder.json",
                                 coder_agent)
        req += 1
    latest_patch = extract_git_diff_swe_rex()
    print("-" * 20 + "PATCH" + "-" * 20)
    print(latest_patch)
    save_trj(f'tjs/{state['repo']}/{state['test_date']}/{state["instance_id"]}/top_plan_{idx}', "coder.json",
             fromat_trace(coder_result["messages"]))
    save_trj(f'tjs/{state['repo']}/{state['test_date']}/{state["instance_id"]}/top_plan_{idx}', "patch.txt",
             latest_patch)
    data = {
        'instance_id': state['instance_id'],
        'model_name_or_path': f'validate_{TEST_DATE}_{REPO}_{idx}',
        'model_patch': latest_patch
    }
    with open(f"tjs/{state['repo']}/{state['test_date']}/workflow_{REPO}_patch_{idx}.jsonl", "a",
              encoding="utf-8") as f:
        import json
        f.write(json.dumps(data, ensure_ascii=False) + "\n")
    state["patch_pool"].append(latest_patch)
    cmd = f"cd {rc.proj_path} && git clean -fd && git reset --hard {state['base_commit']} && chmod -R 777 ."
    run_shell_cmd.invoke({"command": cmd})

    return Command(
        update={
            "patch_pool": state["patch_pool"],
        },
        goto="plan_select"
    )


workflow_builder = StateGraph(CustomState)
workflow_builder.add_edge(START, "input_handler")
workflow_builder.add_node(
    "input_handler",
    input_handler_node
)

workflow_builder.add_node(
    "planer",
    planer
)

workflow_builder.add_node(
    "start_branch",
    start_branch
)

workflow_builder.add_node(
    'dispatcher',
    dispatcher
)

workflow_builder.add_node(
    'sub_worker',
    sub_worker
)

workflow_builder.add_node(
    'plan_select',
    plan_select
)

workflow_builder.add_node(
    "coder",
    coder
)

issue_resolve_graph = workflow_builder.compile()


def main(instance_id: str, commit_id: str, test_instruction):
    thread = {
        "recursion_limit": 350,
        "run_id": uuid.uuid4(),
        "tags": ["interrupt"],
    }
    initial_input = {
        "messages": [
            HumanMessage(
                content=instance_id
            )
        ],
        "preset": "",
        "owner": "",
        "project_name": "",
        "base_commit": commit_id,
        "instance_id": instance_id,
        "final_plans": [],
        "guide": "",
        "final_plan": "",
        "patch_pool": [],
        "tjs_list": [],
        "repo": REPO,
        "test_date": TEST_DATE,
        "test_instruction": test_instruction,
        "test_scheme": ""
    }
    for chunk in issue_resolve_graph.stream(
            initial_input, config=thread, stream_mode="values"
    ):
        if "messages" in chunk and len(chunk["messages"]) > 0:
            chunk["messages"][-1].pretty_print()


# # %%
if __name__ == "__main__":
    os.environ["LANGSMITH_TRACING"] = "false"
    import pandas as pd

    REPO = ""
    TEST_DATE = ""
    # 读取 Parquet 文件

    import json

    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=str, required=True)
    parser.add_argument("--tjs_repo", type=str, required=True)
    parser.add_argument("--tjs_test_date", type=str, required=True)
    parser.add_argument("--instance_id", type=str, required=True)
    args = parser.parse_args()
    require_instance = args.instance_id
    REPO = args.tjs_repo
    TEST_DATE = args.tjs_test_date
    dataset = args.dataset
    df = pd.read_parquet(rf'{dataset}/test-swebench_verified.parquet')
    dict_df = df.to_dict('records')
    i_c = []

    def jsonl_to_dict(path: str) -> dict[str, str]:
        out = {}
        with open(path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                out[obj["instance_id"]] = obj["test_cmd"]
        return out


    test_ins = jsonl_to_dict(rf"{dataset}/data/test_cmd_and_scheme.jsonl")
    for d in dict_df:
        if d['instance_id'] == require_instance:
            i_c.append((d['instance_id'], d['base_commit']))
    for i, c in i_c:
        try:
            tjs_list = []
            plans_list = []
            main(i, c, test_ins[i])
        except Exception as e:
            emsg = str(e)
            data = {
                'instance_id': i,
                'exception': emsg
            }
            with open(
                    f"tjs/{REPO}/{TEST_DATE}/expect_2.jsonl",
                    "a", encoding="utf-8") as f:
                import json

                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        finally:
            asyncio.run(rc.cleanup_swerex())