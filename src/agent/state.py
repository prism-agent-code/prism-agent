"""Defines the custom state structures for the prototype."""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import List, Optional, Annotated, TypedDict
from dataclasses import dataclass, replace
from langgraph.graph import MessagesState, add_messages
from langchain_core.messages import AnyMessage
from operator import add
from langgraph.managed import IsLastStep, RemainingSteps
from pydantic import BaseModel


class SubState(MessagesState):
    index: int
    issue: Optional[str]
    guide: Optional[str]
    trajectory: list[list[AnyMessage]]
    result: Optional[str]
    NUMBER: Optional[int]
    instance_id: Optional[str]
    repo: Optional[str]
    test_date: Optional[str]
    idx_com: Optional[list]
    patches: Optional[list]
    proj_path: Optional[str]
    base_commit: Optional[str]
    date: Optional[str]
    test_instruction: Optional[str]


class CustomState(MessagesState):
    index: int = None
    summary: Optional[str] = None
    preset: Optional[str] = None
    issue: Optional[str] = None
    owner: Optional[str] = None
    project_name: Optional[str] = None
    base_commit: Optional[str] = None
    guide: Optional[str] = None
    solution_mapper_result: Optional[str] = None
    baseline_sha: Optional[str] = None
    patch_pool: Optional[list] = None
    test_instruction: Optional[str] = None
    instance_id: Optional[str] = None
    test_scheme: Optional[str] = None
    final_plan: Optional[str] = None
    tjs_list: Optional[list] = None
    plan_list: Optional[list] = None
    guide_list: Optional[list] = None
    temp_tj: Optional[list] = None
    final_plans: Annotated[list[str], operator.add]
    repo: Optional[str] = None
    test_date: Optional[str] = None
    top_patches: Optional[list] = None
    idx_com: Optional[list] = None
    date: Optional[str] = None


def messages_reducer(left: list, right: list) -> list:
    """Custom messages reducer with incremental caching support.
    
    This reducer automatically marks the last content block in the latest message
    with cache_control to enable incremental caching in multi-turn conversations.
    Only the most recent message will have cache_control to avoid exceeding the
    4-block limit imposed by Anthropic's API.
    """
    # First apply the standard add_messages logic
    result = add_messages(left, right)

    # Remove cache_control from all existing messages
    for message in result:
        if isinstance(message.content, list):
            for content_block in message.content:
                if isinstance(content_block, dict) and "cache_control" in content_block:
                    del content_block["cache_control"]

    if len(result) > 0:
        last_message = result[-1]
        if isinstance(last_message.content, list) and len(last_message.content) > 0:
            last_message.content[-1]["cache_control"] = {"type": "ephemeral"}
        elif isinstance(last_message.content, str):
            # Convert string to list format with cache_control
            last_message.content = [
                {
                    "text": last_message.content,
                    "type": "text",
                    "cache_control": {"type": "ephemeral"},
                }
            ]

    return result
