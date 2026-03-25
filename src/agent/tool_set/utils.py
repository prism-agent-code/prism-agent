import copy
import subprocess
import time
from typing import Any, Optional, TypedDict
from langchain_core.runnables import RunnableConfig
from src.agent import runtime_config
from src.agent.state import CustomState
from src.agent.tool_set.constant import *
from xml.etree.ElementTree import Element, tostring
import json


#############
class PerPlanWorldviewSummary(TypedDict):
    plan_id: str
    worldview_summary: str
    key_evidence: str
    primary_edit_points: list[str]
    main_strategy: str
    core_assumptions: str


class TopWorldviewBranchGuide(TypedDict):
    per_plan_summaries: list[PerPlanWorldviewSummary]
    different_worldview: str


###################

class PerPlanSummary(TypedDict):
    plan_id: str
    approach_summary: str
    modified_files: list[str]
    key_changes: str
    strategy: str
    specific_technique_from_history_solution: str
    specific_files_or_functions: list[str]
    assumptions_made_in_history_solution: str


class Top_branch_guide(TypedDict):
    per_plan_summaries: list[PerPlanSummary]
    component_not_touched_in_history_solution: str
    different_perspective: str
    history_primary_files: str
    history_primary_techniques: str


class Sub_branch_guide(TypedDict):
    per_plan_summaries: list[PerPlanSummary]
    component_not_touched_in_history_solution: str
    different_perspective: str


# [HumanMessage,HumanMessage("")]

tjs_format = "<Trajectory NUMBER={index}>{trajectory}</Trajectory>"
plans_format = "<PLANS NUMBER={index}>{plan}</PLANS>"
patches_format = "<PATCH NUMBER={index}>{patch}</PATCH>"


def format_patches(patches: list) -> str:
    result = ""
    for i, p in enumerate(patches):
        result += patches_format.format(index=i, patch=p)
    return result


def format_plans(plans: list) -> str:
    result = ""
    for i, t in enumerate(plans):
        result += plans_format.format(index=i, plan=t) + '\n'
    return result


##########
def format_worldview_plan_summery(dices: list[dict]):
    temp_format = """About PreviousPlan-{plan_id}:
    Worldview summary:
    {worldview_summary}

    Key evidence:
    {key_evidence}

    Primary edit points:
    {primary_edit_points}

    Main strategy:
    {main_strategy}

    Core assumptions:
    {core_assumptions}
    ----
    """
    result = ""
    for dic in dices:
        result += temp_format.format_map(dic)
    return result


############

def format_plan_summery(dices: list[dict]):
    temp_format = """About PreviousPlan-{plan_id}:
The problem was previously attempted using {approach_summary}. 
It involves modifications to {modified_files}, with key changes such as {key_changes}. 
The core strategy applied was "{strategy}", which may have limitations. 
It relied on {specific_technique_from_history_solution} and focused on {specific_files_or_functions}. 
This approach makes the following assumptions: {assumptions_made_in_history_solution}. 
----
"""
    result = ""
    for dic in dices:
        result += temp_format.format_map(dic)
    return result


def format_tjs(tjs: list) -> str:
    result = ""
    for i, t in enumerate(tjs):
        result += tjs_format.format(index=i,
                                    trajectory=fromat_trace(t, max_len=300, view_content=True, view_usage=False)) + "\n"
    return result




def append_trace(state: CustomState, name: str, new_messages: list, top_k: int):
    new_tj = simplify_langchain_trace(new_messages)
    state[name].append(new_tj)
    tjs_len = len(state[name])
    if tjs_len > top_k:
        print("tjs_len:" + str(tjs_len))
        state[name].pop(0)


def wrap_strings_no_root(strings, item_tag="trace"):
    parts = []
    n = len(strings)
    for i, s in enumerate(strings, start=1):
        el = Element(item_tag, {
            "pos": str(i),  # 位置：从 1 开始
            "age": str(n - i),  # 越小越新；最新为 0
            "newest": "true" if i == n else "false"
        })
        el.text = "" if s is None else str(s)
        parts.append(tostring(el, encoding="unicode", method="xml"))
    return "\n".join(parts)


def _truncate_output(
        text: str | None,
        max_chars: int | None,
) -> str:
    if text is None:
        return ""
    CLIP_NOTICE = "... [TRUNCATED] ..."
    length = len(text)
    if length <= max_chars:
        return text

    # Each side keeps half of MAX_OUTPUT_CHARS
    first = max_chars // 3
    last = first * 2

    head = text[:first]
    tail = text[-last:]

    # 中间用统一的提示信息替代被裁掉的部分
    return f"{head}\n{CLIP_NOTICE}\n{tail}"


def fromat_trace(messages, max_len: int = None, view_content: bool = True, view_usage: bool = True):
    """裁剪消息并输出：对象属性分行 + 列表单行的 JSON 字符串。

    - tool_calls: 仅保留 name/args（不输出 tool_calls[*].intention）
    - intentions: 汇总本条 AIMessage 的所有 intention（与 tool_calls 顺序一致，允许重复）
    - usage_metadata: 当 view_usage=True 时提取（如存在）
    - 规则：
        * AIMessage 无 tool_calls：无论 view_content 如何，只保留 content（不保留 reasoning_content）
        * AIMessage 有 tool_calls：按 view_content 控制是否输出 content/reasoning_content，但始终输出 tool_calls + intentions
    - 特判裁剪（仅当 max_len 不为 None）：
        * tool name == bash: args.command 用 _truncate_output 裁剪
        * tool name == str_replace_editor: args.old_str/new_str/file_text 用 _truncate_output 裁剪
    - 重要：绝不修改传入的 messages/tool_calls/args（会对需要修改的 args 先 deepcopy）
    """

    def S(v):
        return json.dumps(v, ensure_ascii=False, separators=(",", ": "))

    def SL(v):
        return json.dumps(v, ensure_ascii=False, separators=(",", ":"))

    def dumps_obj(d, lvl=0):
        ind, ind2 = "  " * lvl, "  " * (lvl + 1)
        items = []
        for k, v in d.items():
            kjs = json.dumps(k, ensure_ascii=False)
            if isinstance(v, list):
                items.append(f"{ind2}{kjs}:{SL(v)}")
            elif isinstance(v, dict):
                items.append(f"{ind2}{kjs}:{dumps_obj(v, lvl + 1)}")
            else:
                items.append(f"{ind2}{kjs}: {S(v)}")
        return "{\n" + ",\n".join(items) + "\n" + ind + "}"

    def dumps_top(lst):
        body = ",\n".join("  " + dumps_obj(x, 1).replace("\n", "\n  ") for x in lst)
        return "[\n" + body + "\n]"

    def content_str(x):
        if isinstance(x, str):
            return x
        try:
            return json.dumps(x, ensure_ascii=False)
        except Exception:
            return str(x)

    def safe_jsonable(x):
        """把可能不是 JSON-serializable 的对象尽量转成 dict/list/标量；不行就 str(x)。"""
        if x is None or isinstance(x, (str, int, float, bool)):
            return x
        if isinstance(x, dict):
            return {str(k): safe_jsonable(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [safe_jsonable(v) for v in x]
        # 常见：pydantic / dataclass / 自定义对象
        for attr in ("model_dump", "dict", "__dict__"):
            if hasattr(x, attr):
                try:
                    v = getattr(x, attr)
                    obj = v() if callable(v) else v
                    return safe_jsonable(obj)
                except Exception:
                    pass
        try:
            json.dumps(x, ensure_ascii=False)
            return x
        except Exception:
            return str(x)

    def _extract_intention_from_args(args):
        if isinstance(args, dict):
            return args.get("intention")
        if isinstance(args, str):
            try:
                obj = json.loads(args)
            except Exception:
                return None
            if isinstance(obj, dict):
                return obj.get("intention")
        return None

    def _truncate_if_needed(v, max_len_in):
        if max_len_in is None or not isinstance(v, str):
            return v
        return _truncate_output(v, max_len_in)

    def _maybe_parse_args(args):
        """args 可能是 dict 或 JSON str；尽量解析成 dict 便于修改参数。
        返回 (args_obj, parsed_flag)
        """
        if isinstance(args, dict):
            return args, True
        if isinstance(args, str):
            try:
                obj = json.loads(args)
                if isinstance(obj, dict):
                    return obj, True
            except Exception:
                pass
        return args, False

    def norm_tool_calls(tc, max_len_in):
        """输出 tool_calls（仅 name/args），并返回同序 intentions 列表（允许重复）。"""
        if not tc:
            return None, []

        if not isinstance(tc, list):
            tc = [tc]

        out = []
        intentions = []

        for t in tc:
            is_dict = isinstance(t, dict)

            # name/args 可能在顶层，也可能在 function 里
            name = (t.get("name") if is_dict else getattr(t, "name", None))
            args = (t.get("args") if is_dict else getattr(t, "args", None))

            f = (t.get("function") if is_dict else getattr(t, "function", None))
            if (name is None or args is None) and f is not None:
                if name is None:
                    name = (f.get("name") if isinstance(f, dict) else getattr(f, "name", None))
                if args is None:
                    args = (
                            (f.get("arguments") if isinstance(f, dict) else getattr(f, "arguments", None))
                            or (f.get("args") if isinstance(f, dict) else getattr(f, "args", None))
                    )

            if args is None:
                args = (t.get("arguments") if is_dict else getattr(t, "arguments", None))

            # 提取 intention（顶层 or args 内）
            intention = (t.get("intention") if is_dict else getattr(t, "intention", None))
            if intention is None:
                intention = _extract_intention_from_args(args)
            if intention is not None:
                intentions.append(intention)

            # 解析 args，移除 args.intention，并按工具名裁剪（如需）
            args_out = args
            args_obj, parsed = _maybe_parse_args(args)

            if parsed and isinstance(args_obj, dict):
                args_copy = copy.deepcopy(args_obj)
                args_copy.pop("intention", None)

                if max_len_in is not None and name:
                    if name == "bash":
                        if "command" in args_copy:
                            args_copy["command"] = _truncate_if_needed(args_copy.get("command"), max_len_in)
                    elif name == "str_replace_editor":
                        for key in ("old_str", "new_str", "file_text"):
                            if key in args_copy:
                                args_copy[key] = _truncate_if_needed(args_copy.get(key), max_len_in)

                args_out = args_copy

            d = {}
            if name is not None:
                d["name"] = name
            if args_out is not None:
                d["args"] = args_out
            if d:
                out.append(d)

        return (out or None), intentions

    result = []

    for i, m in enumerate(messages):
        max_len_in = max_len

        t = getattr(m, "type", None) or m.__class__.__name__.lower()
        name = getattr(m, "name", None)

        if t == "ai":
            item = {"index": i}
            if name is not None:
                item["name"] = name

            ak = getattr(m, "additional_kwargs", {}) or {}
            tc_raw = getattr(m, "tool_calls", None) or ak.get("tool_calls")

            ntc, intents = norm_tool_calls(tc_raw, max_len_in)
            has_tool_calls = bool(ntc)

            if has_tool_calls:
                item["tool_calls"] = ntc
                if intents:
                    item["intentions"] = intents

                if view_content:
                    item["content"] = content_str(getattr(m, "content", ""))
                    reasoning = ak.get("reasoning_content")
                    if reasoning:
                        item["reasoning_content"] = content_str(reasoning)
            else:
                item["content"] = content_str(getattr(m, "content", ""))

            # ✅ 新增：usage_metadata
            if view_usage:
                usage = getattr(m, "usage_metadata", None)
                if usage is None:
                    usage = ak.get("usage_metadata")
                if usage is not None:
                    item["usage_metadata"] = safe_jsonable(usage)

            result.append(item)

        elif t == "tool":
            item = {"index": i, "type": "tool"}
            if name is not None:
                item["name"] = name
            cont = content_str(getattr(m, "content", ""))
            item["content"] = cont if max_len_in is None else _truncate_output(cont, max_len_in)
            result.append(item)

        elif t == "human":
            item = {"index": i}
            if name is not None:
                item["name"] = name
            item["content"] = content_str(getattr(m, "content", ""))
            result.append(item)

        else:
            item = {"index": i}
            if name is not None:
                item["name"] = name
            item["content"] = content_str(getattr(m, "content", ""))
            result.append(item)

    return dumps_top(result)


def simplify_langchain_trace(messages) -> str:
    """
    精简 LangChain 消息轨迹。
    仅保留这些可能存在于原消息且对重放/复用有用的字段：
      - 通用：type, content, name, id
      - AIMessage：tool_calls（若存在，原样保留）
      - ToolMessage：tool_call_id（若存在，原样保留）
    其它字段（包括所有 token 相关、usage/metadata 等）一律移除。
    返回 json 或 xml 格式的字符串。
    """

    def get_attr(msg, key, default=None):
        # 兼容对象与字典
        if hasattr(msg, key):
            return getattr(msg, key)
        if isinstance(msg, dict):
            return msg.get(key, default)
        return default

    def get_type(msg):
        # LangChain BaseMessage 通常有 .type；没有就用类名兜底（转小写）
        t = get_attr(msg, "type")
        if t:
            return t
        cls = msg.__class__.__name__.lower()
        if "human" in cls: return "human"
        if "ai" in cls: return "ai"
        if "tool" in cls: return "tool"
        if "system" in cls: return "system"
        return "other"

    simplified = []
    for m in messages:
        mtype = get_type(m)
        item = {}

        # 仅保留白名单字段（若存在）
        for k in ("type", "content", "name", "id"):
            v = get_attr(m, k)
            if v is not None:
                item[k] = v
        # 确保 type 与 content 存在（content 必保留）
        item["type"] = item.get("type", mtype)
        item["content"] = get_attr(m, "content", "")

        # AIMessage：保留 tool_calls（原样）
        if mtype == "ai":
            tc = get_attr(m, "tool_calls")
            if tc is None:
                # 有些在 additional_kwargs 中
                ak = get_attr(m, "additional_kwargs", {}) or {}
                tc = ak.get("tool_calls")
            if tc is not None:
                item["tool_calls"] = tc

        # ToolMessage：保留 tool_call_id（原样）
        if mtype == "tool":
            tci = get_attr(m, "tool_call_id")
            if tci is not None:
                item["tool_call_id"] = tci

        simplified.append(item)
    # 默认 JSON
    return json.dumps(simplified, indent=2, separators=(',', ': '))


def get_runtime_config(config: Optional[RunnableConfig] = None) -> Any:
    """Helper function to safely get runtime config.
    
    First tries to get runtime_object from config["configurable"]["runtime_object"].
    Falls back to the global rc if not available.
    
    Args:
        config: RunnableConfig object that might contain runtime_object
        
    Returns:
        RuntimeConfig instance
    """
    if config and isinstance(config, dict) and "configurable" in config:
        runtime_obj = config["configurable"].get("runtime_object")
        if runtime_obj:
            return runtime_obj

    # Fall back to global rc
    return runtime_config.RuntimeConfig()


def maybe_truncate(
        content: str,
        truncate_after: int | None = MAX_RESPONSE_LEN_CHAR,
        truncate_notice: str = CONTENT_TRUNCATED_NOTICE,
) -> str:
    """
    Truncate content and append a notice if content exceeds the specified length.
    """
    return (
        content
        if not truncate_after or len(content) <= truncate_after
        else content[:truncate_after] + truncate_notice
    )


def run_shell_local(
        cmd: str,
        timeout: float | None = 120.0,  # seconds
        truncate_after: int | None = MAX_RESPONSE_LEN_CHAR,
        truncate_notice: str = CONTENT_TRUNCATED_NOTICE,
) -> tuple[int, str, str]:
    """Run a shell command synchronously with a timeout.

    Args:
        cmd: The shell command to run.
        timeout: The maximum time to wait for the command to complete.
        truncate_after: The maximum number of characters to return for stdout and stderr.

    Returns:
        A tuple containing the return code, stdout, and stderr.
    """

    start_time = time.time()

    try:
        process = subprocess.Popen(
            cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )

        stdout, stderr = process.communicate(timeout=timeout)

        return (
            process.returncode or 0,
            maybe_truncate(stdout, truncate_after=truncate_after, truncate_notice=truncate_notice),
            maybe_truncate(
                stderr,
                truncate_after=truncate_after,
                truncate_notice=CONTENT_TRUNCATED_NOTICE,  # Use generic notice for stderr
            ),
        )
    except subprocess.TimeoutExpired:
        process.kill()
        elapsed_time = time.time() - start_time
        raise TimeoutError(f"Command '{cmd}' timed out after {elapsed_time:.2f} seconds")
