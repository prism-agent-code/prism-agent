import os
import subprocess
import time
import asyncio
import uuid
import logging
import shlex
from typing import Annotated, List, Optional, Union, Dict
import ast
from git import Repo
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode
from swerex.runtime.abstract import CreateBashSessionRequest, BashAction, Command, WriteFileRequest, \
    CloseBashSessionRequest
from swerex.deployment.docker import DockerDeployment
from src.agent import runtime_config
from src.agent.runtime_config import RuntimeType
from src.agent.constant import PATCH_RESULT_DIR, RUNTIME_DIR
from src.agent.tool_set.constant import MAX_LIST_FILES, MAX_RESPONSE_LEN_CHAR, FILE_CONTENT_TRUNCATED_NOTICE
from src.agent.tool_set.utils import get_runtime_config
from src.agent.tool_set.edit_tool import str_replace_editor
from swerex.exceptions import CommandTimeoutError
from src.agent.logging_config import get_logger
from pydantic import BaseModel, Field

MAX_OUTPUT_CHARS = 3000


def prepare_input_dir(in_dir, config: RunnableConfig = None):
    # rc = get_runtime_config(config)
    rc = runtime_config.RuntimeConfig()
    assert rc.initialized

    if in_dir == ".":
        in_dir = ""
    return os.path.join(rc.proj_path, in_dir)


def prepare_output_dir(out_dir, config: RunnableConfig = None):
    # rc = get_runtime_config(config)
    rc = runtime_config.RuntimeConfig()
    assert rc.initialized

    return out_dir.replace(rc.proj_path + "/", "")


# Setup logging
logger = get_logger(__name__)


class SearchFilesByKeywordsInput(BaseModel):
    directory: str = Field(
        ...,
        description=(
            "Root directory to search in (relative to repo/project root). "
            "Can also be a file path if you want to search within a single file."
        ),
        min_length=1,
    )
    keywords: Union[List[str], str] = Field(
        ...,
        description=(
            "Regex patterns to search for. Provide either a list of patterns (e.g., ['foo', 'bar.*baz']) "
        ),
    )


@tool(args_schema=SearchFilesByKeywordsInput)
def search_files_by_keywords(
        directory: Annotated[
            str,
            "The root directory to search in, can also be a file path if you want to search keywords within a single "
            "file",
        ],
        keywords: Annotated[
            Union[list[str], str],
            "A list of regex patterns to look for, or a JSON string representation of such a list. Each pattern ",
        ],
        config: RunnableConfig = None,
):
    """
    Recursively searches for files in the given directory (including subdirectories) that contain the specified regex patterns or keywords in their filename or content using ripgrep for faster performance.

    Returns:
        dict: A dictionary where each keyword/pattern maps to a list of file paths and their corresponding line ranges that match the search.
    """

    log_output = []
    if config:
        agent_name = config.get("configurable", {}).get("agent_name")
        log_output.append(f"{agent_name}:")
    else:
        agent_name = None

    # Handle case where keywords comes as a JSON string instead of a list
    if isinstance(keywords, str):
        try:
            import json

            keywords: list = json.loads(keywords)
            if not isinstance(keywords, list):
                return "ArgumentError: The keywords parameter must be a list of strings"
        except (json.JSONDecodeError, TypeError):
            return "ArgumentError: The keywords parameter must be a list of strings, or a valid JSON string representation of a list"

    # Input validation
    if not keywords:
        return "ArgumentError: The keywords must be a non-empty list"

    if len(keywords) > 10:
        return "ArgumentError: The number of keywords must be less than 10"

    # Ensure all keywords are strings
    for i, keyword in enumerate(keywords):
        if not isinstance(keyword, str):
            return f"ArgumentError: All keywords must be strings, but item {i} is {type(keyword).__name__}"
        if len(keyword) < 2:
            return f"ArgumentError: The keyword '{keyword}' must be at least 2 characters long"
    directory = prepare_input_dir(directory, config)
    try:
        subprocess.run(
            ["rg", "--version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return "Error: ripgrep is not installed or not available in PATH. Please install ripgrep for this tool to work."

    # Make sure directory exists
    if not os.path.exists(directory):
        return f"Error: Directory or file '{directory}' does not exist"
    else:
        log_output.append(f"--search under: {directory}")

    # Initialize results dictionary
    results = {}

    # Search for each keyword
    for keyword in keywords:
        matching_files = []

        try:
            rg_cmd = [
                "rg",
                "--line-number",  # 一定有行号
                "--no-heading",  # 不要 group heading，用 grep 风格
                "--with-filename",  # 即使只有一个文件，也总是带文件名
                "--no-column",  # 不要列号，避免多一个冒号
                "--color", "never",  # 去掉颜色，方便解析（可选）
            ]

            # Add filename matching capability (search in filenames too)
            if os.path.isfile(directory):
                # Check if the filename contains the keyword
                if keyword in os.path.basename(directory):
                    matching_files.append(prepare_output_dir(directory, config))
            else:
                try:
                    file_pattern_cmd = ["rg", "--files", "-g", f"*{keyword}*"]
                    file_proc = subprocess.run(
                        file_pattern_cmd + [directory],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        check=False,
                    )
                    # Add files that match by name
                    for file_path in file_proc.stdout.splitlines():
                        matching_files.append(prepare_output_dir(file_path, config))
                except subprocess.SubprocessError as e:
                    print(f"Error searching filenames: {e}")

            search_target = directory

            process = subprocess.run(
                rg_cmd + ["-e", keyword, "--", search_target],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            file_line_map = {}
            for line in process.stdout.splitlines():
                try:
                    # Skip empty lines
                    if not line.strip():
                        continue

                    parts = line.split(":", 2)
                    if len(parts) >= 2:
                        file_path = parts[0]
                        try:
                            line_number = int(parts[1])
                            if file_path not in file_line_map:
                                file_line_map[file_path] = {
                                    "first": line_number,
                                    "last": line_number,
                                }
                            else:
                                file_line_map[file_path]["last"] = line_number
                        except ValueError:
                            # Skip lines where line number can't be parsed
                            continue
                except Exception as e:
                    print(f"Error: processing line '{line}': {e}")

            # Format results
            for file_path, line_info in file_line_map.items():
                output_path = prepare_output_dir(file_path, config)
                if line_info["first"] == line_info["last"]:
                    matching_files.append(f"{output_path}: line {line_info['first']}")
                else:
                    matching_files.append(
                        f"{output_path}: line {line_info['first']}-{line_info['last']}"
                    )

                # Check if we've reached the maximum files limit
                if len(matching_files) >= MAX_LIST_FILES:
                    matching_files.insert(
                        0,
                        f"Note: Too many files found. Only the first {MAX_LIST_FILES} files are returned, please narrow down your search",
                    )
                    break

        except Exception as e:
            matching_files.append(f"Error: {str(e)}")

        results[keyword] = matching_files
        log_output.append(f"----keyword: {keyword} Matches: {len(matching_files)}")

    print("\n".join(log_output))
    return results


class ViewDirectoryInput(BaseModel):
    dir_path: str = Field(
        default="./",
        description="Directory path relative to the repository root (git root).",
    )
    depth: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Maximum traversal depth. If None, the tool will choose an appropriate depth and "
            "automatically reduce it if the number of entries exceeds MAX_LIST_FILES."
        ),
    )


@tool(args_schema=ViewDirectoryInput)
def view_directory(dir_path: str = "./", depth: Optional[int] = None,
                   config: RunnableConfig = None) -> str:
    """
    View the file structure of the repository, including directories (marked with /).
    Automatically reduces depth if entries exceed MAX_LIST_FILES.
    Returns:
        str: A newline-joined, sorted list of directories (with /) and files.
    """
    # if not intention.strip():
    #     return "Notice: Args intention is Required!!!"
    print("---------view_directory-----------")
    if dir_path == '.':
        dir_path = './'
    log_output = []
    if config:
        agent_name = config.get("configurable", {}).get("agent_name")
        log_output.append(f"{agent_name}:")
    else:
        agent_name = None

    log_output.append(f"--view_directory: {dir_path} depth: {depth}")

    # rc = get_runtime_config(config)
    rc = runtime_config.RuntimeConfig()
    assert rc.initialized

    # Normalize dir_path to ensure proper filtering
    #
    if dir_path.startswith("./"):
        processed_dir = dir_path[2:]
    else:
        processed_dir = dir_path

    if processed_dir:
        processed_dir = processed_dir.rstrip("/") + "/"

    # Fetch all files in the repository
    file_list = []
    if rc.runtime_type == RuntimeType.LOCAL:
        repo = Repo(rc.proj_path)
        file_list = [entry.path for entry in repo.commit().tree.traverse()]
    elif rc.runtime_type == RuntimeType.SWEREX:
        runtime = rc.swe_rex_deployment.runtime
        result = asyncio.run(runtime.run_in_session(BashAction(command="git ls-files", check="ignore")))
        file_list = [line.strip() for line in result.output.splitlines()]
    else:
        raise ValueError("Unsupported runtime type")

    # Filter out .git and its subfolders/files
    file_list = [p for p in file_list if not (p == ".git" or p.startswith(".git/"))]

    # Filter out all hidden files and directories (those starting with a dot at any level)
    file_list = [p for p in file_list if
                 not (os.path.basename(p).startswith(".") or any(part.startswith(".") for part in p.split("/")))]

    # Collect files and directories with their depths
    all_files = []  # Format: (full_path, depth) 存的是文件
    all_dirs = set()  # Format: (full_dir_path, depth) 存的是文件夹

    for path in file_list:
        # Filter files outside the target directory
        if not path.startswith(processed_dir):
            continue

        # Calculate file depth
        rel_path = path[len(processed_dir):] if processed_dir else path
        file_depth = rel_path.count("/")
        all_files.append((path, file_depth))

        # Generate parent directories from the file path
        dir_components = rel_path.split("/")[:-1]  # Exclude filename
        current_dir = []
        for component in dir_components:
            current_dir.append(component)
            dir_rel_path = "/".join(current_dir)
            dir_depth = dir_rel_path.count("/")  # Depth is based on slashes
            full_dir_path = f"{processed_dir}{dir_rel_path}/"
            all_dirs.add((full_dir_path, dir_depth))

    # Function to filter entries by depth
    def filter_entries(max_depth: Optional[int]) -> List[str]:
        # Filter files
        filtered_files = [path for path, d in all_files if (max_depth is None) or (d <= max_depth)]
        # Filter directories
        filtered_dirs = [dir_path for dir_path, d in all_dirs if (max_depth is None) or (d <= max_depth)]
        # Combine and deduplicate
        entries = list(set(filtered_dirs + filtered_files))
        return sorted(entries)  # Alphabetical order

    # Check initial entry count
    initial_entries = filter_entries(depth)
    if len(initial_entries) <= MAX_LIST_FILES:
        log_output.append(f"----depth: {depth} entries: {len(initial_entries)}")
        logger.info("\n".join(log_output))
        return "\n".join(initial_entries)

    # Automatically reduce depth
    start_depth = (
        depth
        if depth is not None
        else max(max((d for _, d in all_files), default=0), max((d for _, d in all_dirs), default=0))
    )

    for d in range(start_depth, -1, -1):
        adjusted_entries = filter_entries(d)
        if len(adjusted_entries) <= MAX_LIST_FILES:
            log_output.append(f"----reduced depth: {d} entries: {len(adjusted_entries)}")
            logger.info("\n".join(log_output))
            return f"Note: Reduced depth to {d} with {len(adjusted_entries)} entries:\n" + "\n".join(adjusted_entries)

    # Fallback (depth 0)
    final_entries = filter_entries(0)

    log_output.append(f"----fallback depth: 0 entries: {len(final_entries)}")
    logger.info("\n".join(log_output))

    return f"Note: Limited to depth 0 with {len(final_entries)} entries\n" + "\n".join(final_entries)


class ViewFileStructureInput(BaseModel):
    file_path: str = Field(
        ...,
        description="Path to a Python file relative to the project root (e.g., 'src/main.py'). Must end with '.py'.",
        min_length=1,
        pattern=r".*\.py$",
    )


@tool(args_schema=ViewFileStructureInput)
def view_file_structure(
        file_path: Annotated[
            str,
            "Path to a Python file relative to the project root (e.g., 'src/main.py')"
        ],
        config: RunnableConfig = None
) -> str:
    """Extracts and displays the hierarchical structure of a Python file. Ideally suited for files that are too large to view directly.
    
    Parses the specified Python file and returns a formatted representation of:
    - Classes with line numbers and docstrings
    - Methods with parameters, line numbers, and docstrings
    - Functions with parameters, line numbers, and docstrings
    
    Line numbers can help identify the exact range of code within a file, which can then be viewed using the `view` command with range in the `str_replace_editor` tool.
    
    The indentation in the output indicates the nesting level:
    
    Class: ClassName (line X)
    -- Doc: Class docstring
    -- Method: method_name(param1, param2) (line Y)
    ---- Doc: Method docstring
    Function: function_name(param1, param2) (line Z)
    -- Doc: Function docstring
    
    Returns:
        A formatted string representing the file's structure with indentation showing the hierarchy.
    """
    # if not python file, return error message
    if not file_path.endswith('.py'):
        return "View file structure failed. Currenly only support python file."
    rc = runtime_config.RuntimeConfig()
    # rc = get_runtime_config(config)
    assert rc.initialized

    if rc.runtime_type == RuntimeType.LOCAL:
        full_file_path = os.path.join(rc.proj_path, file_path)
        if not os.path.isfile(full_file_path):
            raise ValueError(f"file_name: '{file_path}' doesn't exist!")
        with open(full_file_path, encoding="utf-8") as f:
            file_content = f.read()  # FIXME : add line number
    if rc.runtime_type == RuntimeType.SWEREX:
        runtime = rc.swe_rex_deployment.runtime
        safe_path = shlex.quote(file_path)

        # 1. 用 shell 自己检查文件是否存在，避免 cat 直接失败
        cmd = (
            f"if [ -f {safe_path} ]; then "
            f"  cat {safe_path}; "
            f"else "
            f"  echo '__FILE_NOT_FOUND__'; "
            f"fi"
        )

        # 2. check='silent'，不要让 SWE-ReX 为非零 exit code 直接抛异常
        action = BashAction(command=cmd, check="silent")
        obs = asyncio.run(runtime.run_in_session(action))

        output = obs.output or ""

        if "__FILE_NOT_FOUND__" in output:
            # 和 LOCAL 分支的语义统一：文件不存在时给 LLM 返回可读错误，而不是抛异常
            return f"View file structure failed. file_name: '{file_path}' doesn't exist in repo."

        file_content = output

    return parse_content_structure(file_content)


MAX_DOC_CHARS = 160


def _shorten_doc(doc: str, max_chars: int = MAX_DOC_CHARS) -> str:
    one_line = " ".join(doc.splitlines())
    if len(one_line) <= max_chars:
        return one_line
    return one_line[:max_chars] + " ... [truncated]"


def parse_content_structure(file_content: str) -> str:
    tree = ast.parse(file_content)
    outline_str = ""

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            class_name = f"Class: {node.name} (line {node.lineno})"
            class_doc = ast.get_docstring(node) or None
            outline_str += f"{class_name}\n"
            if class_doc:
                outline_str += f"-- Doc: {_shorten_doc(class_doc)}\n"

            for n in node.body:
                if isinstance(n, ast.FunctionDef):
                    method_args = [arg.arg for arg in n.args.args]
                    method_name = f"-- Method: {n.name}({', '.join(method_args)}) (line {n.lineno})"
                    method_doc = ast.get_docstring(n) or None
                    outline_str += f"{method_name}\n"
                    if method_doc:
                        outline_str += f"---- Doc: {_shorten_doc(method_doc)}\n"

        elif isinstance(node, ast.FunctionDef):
            func_args = [arg.arg for arg in node.args.args]
            func_name = f"Function: {node.name}({', '.join(func_args)}) (line {node.lineno})"
            func_doc = ast.get_docstring(node) or None
            outline_str += f"{func_name}\n"
            if func_doc:
                outline_str += f"-- Doc: {_shorten_doc(func_doc)}\n"

    return outline_str or "[Empty file or no top-level classes/functions]"


def extract_git_diff_local():
    """Executes and returns the `git diff` command in a local runtime environment."""
    rc = runtime_config.RuntimeConfig()
    print("extracting git diff local")
    rc.pretty_print_runtime()
    assert rc.initialized
    assert rc.runtime_type == runtime_config.RuntimeType.LOCAL

    import subprocess

    process = subprocess.Popen(
        r"/bin/bash",
        cwd=rc.proj_path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        shell=True,
    )
    out, err = process.communicate(
        "git -c core.fileMode=false diff --exit-code --no-color"
    )
    return out


def extract_git_diff_swe_rex(base_commit: str = None):
    rc = runtime_config.RuntimeConfig()
    runtime = rc.swe_rex_deployment.runtime

    proj = shlex.quote(rc.proj_path)
    env = "export PAGER=cat GIT_PAGER=cat LESS=FRX TERM=dumb"
    if not base_commit:
        command = (
            f"{env} && git -C {proj} --no-pager -c core.fileMode=false "
            "diff --exit-code --no-color"
        )
    else:
        base = shlex.quote(base_commit)
        command = (
            "export PAGER=cat GIT_PAGER=cat LESS=FRX TERM=dumb"
            f" && git -C {proj} --no-pager -c core.fileMode=false diff --no-color --binary --diff-filter=a {base}"
        )
    try:
        asyncio.run(runtime.close_session(CloseBashSessionRequest()))
    except Exception as e:
        logger.error(f"Error closing session after timeout: {e}")

    try:
        asyncio.run(runtime.create_session(CreateBashSessionRequest()))
    except Exception as e:
        logger.error(f"Error creating new session after timeout: {e}")
    try:
        asyncio.run(runtime.run_in_session(BashAction(command="cd /", check="silent", timeout=10)))
    except Exception:
        pass

    try:
        cmd_output = asyncio.run(
            runtime.run_in_session(BashAction(command=command, check="silent", timeout=120))
        )
    except CommandTimeoutError:
        return ""

    return cmd_output.output


def save_git_diff(git_diff_output_before: str):
    print("Saving git diff")
    rc = runtime_config.RuntimeConfig()
    instance_id = rc.proj_name.replace("/", "+")
    print("-" * 15 + "look diff is true" + "-" * 15)
    print(git_diff_output_before)
    patch_path = (
            os.path.join(PATCH_RESULT_DIR, instance_id + "@" + str(int(time.time())))
            + ".patch"
    )

    with open(patch_path, "w", encoding="utf-8") as save_file:
        save_file.write(git_diff_output_before)
    return git_diff_output_before


import json
import re


def _normalize_view_range(
        view_range: Optional[Union[List[int], str]],
) -> Optional[List[int]]:
    """
    Return [start, end] exactly as provided (after parsing).
    - None/"" -> None (view full file)
    - "a-b" -> [a, b]   (不会把 b 当成负数)
    - "[a, b]" -> [a, b]
    - "a,b" / "a b" -> [a, b]
    """
    if view_range is None:
        return None

    if isinstance(view_range, (list, tuple)):
        if len(view_range) != 2:
            raise ValueError(f"view_range must have 2 items, got {len(view_range)}")
        return [int(view_range[0]), int(view_range[1])]

    if isinstance(view_range, str):
        s = view_range.strip()
        if not s:
            return None

        # 1) 处理 "a-b"（避免把 - 当负号）
        m = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", s)
        if m:
            return [int(m.group(1)), int(m.group(2))]

        # 2) JSON: "[a, b]"
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list) and len(parsed) == 2:
                return [int(parsed[0]), int(parsed[1])]
        except json.JSONDecodeError:
            pass

        # 3) 兜底：提取两个非负整数（"a,b" / "a b" / "start=a end=b"）
        nums = re.findall(r"\d+", s)
        if len(nums) >= 2:
            return [int(nums[0]), int(nums[1])]

        raise ValueError(f"Cannot parse view_range: {view_range!r}")

    raise TypeError(f"view_range must be list|str|None, got {type(view_range)}")


class ViewFileContentInput(BaseModel):
    file_name: str = Field(
        ...,
        description="File path relative to the git repository root (git root). Candidates can be obtained via `view_directory`.",
        min_length=1,
    )
    view_range: Optional[Union[List[int], str]] = Field(
        default=None,
        description=(
            "Optional line range to view. Accepts either a list [start_line, end_line] "
            "If omitted, the tool views the whole file."
        ),
    )


@tool(args_schema=ViewFileContentInput)
def view_file_content(
        file_name: Annotated[
            str,
            "File name relative to git root, candidates can be retrieved by `view_directory`",
        ],
        view_range: Annotated[
            Optional[Union[List[int], str]],
            "Optional parameter [start_line, end_line] to specify the range of lines to view",
        ] = None,
        config: RunnableConfig = None,
) -> str:
    """
    Read the content of the specified file.
    Parameters:
        file_name (str): File name relative to the git root directory.
        view_range (Optional[List[int]]): Optional list containing [start_line, end_line] to limit the lines displayed.
    Usage:
        - LLM should initially attempt to read the entire file content.
        - If the file is too large, LLM can use the `view_file_structure` tool to identify relevant code ranges,
          and then call this tool again specifying the `view_range` to read only the necessary lines.
    Returns:
        str: Content of the file or the specified line range.
    """
    try:
        view_range = _normalize_view_range(view_range)
    except Exception as e:
        # 解析 view_range 失败就直接返回错误
        return f"view_file_content error: invalid view_range={view_range!r}. {type(e).__name__}: {e}"

    rc = runtime_config.RuntimeConfig()
    log_output = []

    if config:
        agent_name = config.get("configurable", {}).get("agent_name")
        log_output.append(f"{agent_name}:")
    else:
        agent_name = None

    # rc = get_runtime_config(config)
    assert rc.initialized

    if view_range:
        return str_replace_editor.invoke({"command": "view", "path": file_name, "line_range": view_range},
                                         config=config)
    else:
        return str_replace_editor.invoke({"command": "view", "path": file_name}, config=config)


CLIP_NOTICE = (
    "... [TRUNCATED] ..."
)


def _truncate_output(
        text: str | None,
) -> str:
    if text is None:
        return ""

    length = len(text)
    if length <= MAX_OUTPUT_CHARS:
        return text

    # Each side keeps half of MAX_OUTPUT_CHARS
    first = MAX_OUTPUT_CHARS // 2
    last = first * 2

    head = text[:first]
    tail = text[-last:]

    return f"{head}\n{CLIP_NOTICE}\n{tail}"


class RunShellCmdInput(BaseModel):
    command: str = Field(
        ...,
        description=(
            "A bash shell command to run from the project root. "
            "No internet access. Avoid very large outputs."
        ),
        min_length=1,
    )

@tool("bash", args_schema=RunShellCmdInput)
def run_shell_cmd(
        command: Annotated[str, "A shell command to be run"],
        config: RunnableConfig = None,
) -> str:
    """
    You are already in the root directory and do not need to navigate.
    Run commands in a bash shell (agent use)
    * When invoking this tool, the contents of the "command" parameter does NOT need to be XML-escaped.
    * You don't have access to the internet via this tool.
    * You do have access to a mirror of common linux and python packages via apt and pip.
    * State is persistent across command calls and discussions with the user.
    * To inspect a particular line range of a file, e.g. lines 10-25, try 'sed -n 10,25p /path/to/the/file'.
    * Please avoid commands that may produce a very large amount of output.
    * Please run long lived commands in the background, e.g. 'sleep 10 &' or start a server in the background.
    * If behavior may vary across releases, you can run command queries to check the relevant project/package version let it guide your approach.

    Returns:
        str: The stdout results of the command
    """

    rc = runtime_config.RuntimeConfig()
    assert rc.initialized

    proj_path = rc.proj_path
    logger.info(f"run_shell_cmd using project path: {proj_path}")

    if rc.runtime_type == RuntimeType.LOCAL:
        import subprocess
        conda_env_name = ""
        if conda_env_name:
            # 若 command 需要 shell 特性（如管道/重定向/变量展开），用 bash -lc 托管：
            cmd = ["conda", "run", "-n", conda_env_name, "--no-capture-output", "bash", "-lc", command]
        else:
            cmd = ["bash", "-lc", command]

        res = subprocess.run(
            cmd,
            cwd=proj_path,
            text=True,
            capture_output=True,
            check=False
        )

        if res.returncode != 0:
            raise RuntimeError(f"[run_shell_cmd] returncode={res.returncode}\nSTDERR:\n{res.stderr}")
        return res.stdout

    elif rc.runtime_type == RuntimeType.SWEREX:
        runtime = rc.swe_rex_deployment.runtime
        try:
            cmd_output = asyncio.run(runtime.run_in_session(BashAction(command=command, check="silent", timeout=60)))
        except CommandTimeoutError:
            # Close the current session and create a new one, then rerun the command
            logger.warning("Timeout error, trying closing session and creating new one")

            def _best_effort_reset():
                try:
                    asyncio.run(runtime.close_session(CloseBashSessionRequest()))
                except Exception as e:
                    logger.error(f"Error closing session after timeout: {e}")
                try:
                    asyncio.run(runtime.create_session(CreateBashSessionRequest()))
                    asyncio.run(
                        runtime.run_in_session(BashAction(command=f"cd {rc.proj_path}", check="silent", timeout=10)))
                except Exception as e:
                    logger.error(f"Error creating new session after timeout: {e}")

            # Retry the command once, but catch timeout error on retry as well
            _best_effort_reset()
            try:
                cmd_output = asyncio.run(
                    runtime.run_in_session(BashAction(command=command, check="silent", timeout=120)))
            except CommandTimeoutError as ee:
                _best_effort_reset()
                # 统一：超时 → 抛异常（而不是返回字符串）
                return str(
                    f"[run_shell_cmd] timed out after 120s: {command}"
                )
        except BaseExceptionGroup as eg:
            sub = eg.exceptions[0] if getattr(eg, "exceptions", None) else eg
            return f"[run_shell_cmd] BaseExceptionGroup: {type(sub).__name__}: {sub}"
        except Exception as e:
            return f"[run_shell_cmd] exception: {type(e).__name__}: {e}"
        if getattr(cmd_output, "exit_code", 0) != 0:
            failure = getattr(cmd_output, "failure_reason", "") or ""
            out = getattr(cmd_output, "output", "") or ""
            # 对错误信息也做截断，尤其是 output
            truncated_failure = _truncate_output(failure)
            truncated_out_tail = _truncate_output(out)

            return (
                f"[run_shell_cmd] returncode={cmd_output.exit_code}\n"
                f"STDERR/Reason (maybe truncated):\n{truncated_failure}\n"
                f"STDOUT (tail, maybe truncated):\n{truncated_out_tail}"
            )
        return _truncate_output(cmd_output.output or "")

    else:
        raise ValueError("Unsupported runtime type")


@tool
def submit():
    """Finalize the current task and submit your work.
Call this when you have completed your implementation and verification,
or when you cannot make further meaningful progress. After calling this tool,
you must stop reading, editing, or testing anything for this task."""
    rc = runtime_config.RuntimeConfig()
    rc.have_submit = True
    return "Your repair results have been submitted."


# todo 一开始就做plan是不是太早后续考虑删除plan字段
@tool
def think(
        thought: Annotated[str, "The thought to log."], config: RunnableConfig = None
) -> str:
    """Use the tool to think about something. It will not obtain new information or make any changes to the repository, but just log the thought. Use it when complex reasoning or brainstorming is needed.

    Common use cases:
    1. When exploring a repository and discovering the source of a bug, call this tool to brainstorm several unique ways of fixing the bug, and assess which change(s) are likely to be simplest and most effective.
    2. After receiving test results, use this tool to brainstorm ways to fix failing tests.
    3. When planning a complex refactoring, use this tool to outline different approaches and their tradeoffs.
    4. When designing a new feature, use this tool to think through architecture decisions and implementation details.
    5. When debugging a complex issue, use this tool to organize your thoughts and hypotheses.

    The tool simply logs your thought process for better transparency and does not execute any code or make changes.
    """
    return "Your thought has been logged. Please continue your work.\n"
