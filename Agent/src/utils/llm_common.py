"""
婉情AI - DeepSeek 客户端共享单例（generate_reply / fuse_emotion 共用）
======================================================================
此前两个节点各自维护一份延迟初始化副本（fuse_emotion 版还缺 timeout），
统一收敛到此处：全 Agent 唯一的 LLM 客户端入口。

使用方式：
    from src.utils.llm_common import get_deepseek_client
    client = get_deepseek_client()
"""

from typing import Optional

_client: Optional["object"] = None


def get_deepseek_client():
    """获取全局唯一的 DeepSeek ChatOpenAI 客户端（延迟初始化，统一超时）。"""
    global _client
    if _client is None:
        from langchain_openai import ChatOpenAI

        from config import llm_config

        _client = ChatOpenAI(
            model=llm_config.CHAT_MODEL,
            api_key=llm_config.API_KEY,
            base_url=llm_config.BASE_URL,
            temperature=llm_config.TEMPERATURE,
            max_tokens=llm_config.MAX_TOKENS,
            timeout=llm_config.TIMEOUT,  # 显式超时，避免无限等待
        )
    return _client
