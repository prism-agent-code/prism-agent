
import asyncio
from dataclasses import dataclass
import json
import logging
import os
from pprint import pprint
import re
import time
from typing import List, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
import yaml

from src.agent import runtime_config
from src.agent.logging_config import get_logger
from src.agent.runtime_config import RuntimeConfig, RuntimeType
# from agent.tool_set.utils import get_runtime_config
from src.utils.format_utils import format_analysis_for_llm

# Setup logging
logger = get_logger(__name__)


"""
Defines various util functions for the prototype."""


class UndefinedValueError(ValueError):
    """
    A custom exception raised when a variable is not defined.

    Args:
        variable_name (str): The name of the undefined variable
        message (str, optional): Custom error message
    """

    def __init__(self, variable_name, message=None):
        if message is None:
            message = f"`{variable_name}` is required and not defined in `.env` environment variables."

        self.variable_name = variable_name

        super().__init__(message)