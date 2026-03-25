"""
Defines the LLM based on the `LLM_PROVIDER` and `LLM_MODEL` env vars.
"""

import os

from langchain_anthropic import ChatAnthropic
from langchain_deepseek import ChatDeepSeek
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from src.agent.utils import UndefinedValueError

from src.agent.runtime_config import load_env_config



load_env_config()


def create_llm(llm_provider: str = "deepseek", llm_name: str = "deepseek-chat", max_token: int = None,
               temperature: float = 0.0):
    """Creates the LLM according to `LLM_PROVIDER` and `LLM_MODEL` env vars"""
    created_llm = None
    if not llm_provider:
        raise UndefinedValueError("LLM_PROVIDER")
    if "openai" in llm_provider.lower():
        created_llm = ChatOpenAI(
            model=llm_name, temperature=temperature, max_tokens=max_token, cache=False
        )
    elif "anthropic" in llm_provider.lower():
        created_llm = ChatAnthropic(
            model=llm_name, temperature=0.0, max_tokens=max_token, cache=False
        )
    elif "deepseek" in llm_provider.lower():
        if llm_name == 'deepseek-speciale':
            created_llm = ChatDeepSeek(
                model='deepseek-reasoner', api_key='', temperature=temperature,
                max_tokens=max_token, cache=False,
                base_url='https://api.deepseek.com/v3.2_speciale_expires_on_20251215',
            )
        else:
            created_llm = ChatDeepSeek(
                model=llm_name, api_key='', temperature=temperature,
                max_tokens=max_token, cache=False
            )
    elif "qwen" in llm_provider.lower():
        created_llm = ChatOpenAI(
            model=llm_name,
            api_key="",
            base_url="",
            temperature=temperature,
            max_tokens=max_token,
            cache=False
        )
    elif "kimi" in llm_provider.lower():
        created_llm = ChatOpenAI(
            api_key='',
            base_url="https://api.moonshot.cn/v1",
            model=llm_name,
            temperature=temperature,
            max_tokens=max_token
        )
    elif "gemini" in llm_provider.lower():
        created_llm = ChatOpenAI(
            model="gemini-3-pro-preview",
            api_key="",
            base_url="",
            temperature=temperature,
            max_tokens=max_token,
            cache=False
        )

    if not created_llm or not llm_name:
        raise UndefinedValueError("LLM_MODEL")
    return created_llm


llm = create_llm(llm_provider="deepseek", max_token=4096)

mapper_llm = create_llm(llm_provider='deepseek', llm_name='deepseek-reasoner', temperature=0.0)
reviewer_llm = create_llm(llm_provider='deepseek', temperature=0.0, llm_name="deepseek-reasoner")
coder_llm = create_llm(llm_provider='deepseek', llm_name='deepseek-reasoner', temperature=0.0)

if __name__ == "__main__":
    print(selector_llm.invoke("Tell me a joke"))
