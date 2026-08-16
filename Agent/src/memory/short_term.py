"""
婉情AI - 短期工作记忆 (Short-Term Working Memory)
==================================================
职责：与 Redis 交互，维护对话上下文。
特性：
 - Python 主要作为读取方，获取上下文注入 Prompt。
 - Java 侧负责在用户发送消息、以及接收到 AI 响应后，将最新消息写入 Redis List。
 - Python 侧提供 `summarize_history` 机制，当消息达到上限时，由 Python 执行大模型摘要，
   然后将摘要存入长期记忆 (Chroma)，并删减 Redis 队列（此高阶操作保留写入权限）。
"""

import json
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from config import redis_config, llm_config
from src.utils.logger import logger
from src.utils.redis_client import get_redis
from src.models.schemas import ConversationMessage

# ==============================================================================
# 短期记忆读取
# ==============================================================================

async def get_recent_history(session_id: str, limit: int = 10) -> list[ConversationMessage]:
    """
    读取最近 N 条原始对话。

    Args:
        session_id: 会话 ID
        limit: 读取条数

    Returns:
        对话消息列表（按时间正序排列）
    """
    key = redis_config.history_key(session_id)
    try:
        r = await get_redis()
        # Redis List 头部(0)是最新的，获取最近 limit 条
        # 注意：lrange(0, limit-1) 取出的是从新到旧的顺序
        raw_msgs = await r.lrange(key, 0, limit - 1)
        
        messages = []
        for raw in raw_msgs:
            try:
                data = json.loads(raw)
                messages.append(ConversationMessage(**data))
            except Exception as e:
                logger.warning(f"[short_term] 解析历史消息失败: {e}")
                
        # 翻转顺序，使其符合人类阅读的时间正序 (先旧后新)
        return messages[::-1]
    
    except Exception as e:
        logger.error(f"[short_term] 读取 Redis 历史失败: {e}")
        return []

async def get_session_summary(session_id: str) -> str:
    """获取当前会话的累积摘要"""
    key = redis_config.summary_key(session_id)
    try:
        r = await get_redis()
        summary = await r.get(key)
        return summary or ""
    except Exception as e:
        logger.error(f"[short_term] 读取 Redis 摘要失败: {e}")
        return ""

# ==============================================================================
# 历史压缩与摘要 (异步任务)
# ==============================================================================

async def check_and_summarize_history(session_id: str, user_id: str) -> None:
    """
    检查对话长度，超过阈值则触发摘要并归档到长期记忆。
    该函数由后台异步运行，不阻塞主对话响应。
    """
    history_key = redis_config.history_key(session_id)
    summary_key = redis_config.summary_key(session_id)
    limit = redis_config.SUMMARY_TRIGGER_COUNT  # e.g., 20
    keep = redis_config.SUMMARY_KEEP_COUNT      # e.g., 5

    try:
        r = await get_redis()
        length = await r.llen(history_key)
        
        if length < limit:
            return  # 未达阈值，无需压缩

        logger.info(f"[short_term] 会话 {session_id} 历史长度({length})达到阈值，开始压缩...")

        # 取出所有需要被压缩的旧消息 (排除我们要保留的最新 keep 条)
        raw_to_compress = await r.lrange(history_key, keep, -1)
        if not raw_to_compress:
            return

        # 构造文本
        msgs_to_compress = []
        for raw in raw_to_compress[::-1]:  # 转为正序
            data = json.loads(raw)
            msgs_to_compress.append(f"{data.get('role', 'unknown')}: {data.get('content', '')}")
        text_to_compress = "\n".join(msgs_to_compress)

        # 读取已有摘要
        old_summary = await get_session_summary(session_id)

        # 调用 LLM 进行增量摘要
        new_summary = await _generate_incremental_summary(old_summary, text_to_compress)

        # 事务执行：更新摘要，并裁剪列表
        async with r.pipeline(transaction=True) as pipe:
            pipe.set(summary_key, new_summary)
            # 保留头部（即最新的）keep 条消息，0 是最新，keep-1 是第 keep 条
            pipe.ltrim(history_key, 0, keep - 1)
            await pipe.execute()

        logger.info(f"[short_term] 会话 {session_id} 压缩完成，摘要已更新，删减了 {len(raw_to_compress)} 条记录")

        # 异步存入 Chroma 长期记忆 (作为中间态保存)
        from src.memory.long_term import store_long_term_memory
        from src.models.schemas import MemoryType
        await store_long_term_memory(
            user_id=user_id,
            content=new_summary,
            memory_type=MemoryType.CONVERSATION_SUMMARY,
            metadata={"session_id": session_id}
        )

    except Exception as e:
        logger.error(f"[short_term] 会话压缩任务失败: {e}")


async def _generate_incremental_summary(old_summary: str, new_dialogue: str) -> str:
    """调用 DeepSeek 进行增量总结"""
    system_prompt = """你是一个专业的长上下文总结助手。
请根据【之前的摘要】和【新增的对话】，将其浓缩为一个连贯的【最新摘要】。
要求：
- 提取用户情绪变化、暴露的问题、以及 AI 采取的干预措施。
- 保持客观简练，不要遗漏关键事实（如提到的事件、姓名、偏好）。
"""
    human_prompt = f"【之前的摘要】\n{old_summary or '无'}\n\n【新增的对话】\n{new_dialogue}\n\n请输出最新摘要："

    client = ChatOpenAI(
        model=llm_config.CHAT_MODEL,
        api_key=llm_config.API_KEY,
        base_url=llm_config.BASE_URL,
        temperature=0.3,
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", human_prompt)
    ])
    
    chain = prompt | client
    response = await chain.ainvoke({})
    return response.content.strip()


# ==============================================================================
# 短期记忆写入（追加对话消息）
# ==============================================================================

async def append_conversation_turn(
    session_id: str,
    role: str,
    content: str,
) -> None:
    """
    向 Redis List 追加一条对话消息（短期记忆追加）。

    写入方：LangGraph log_session_node（Python Agent 侧）
    读取方：Java 侧主动读取，或 Python 侧查询历史

    Args:
        session_id: 会话 ID
        role: 角色，"user" 或 "ai"
        content: 消息内容
    """
    key = redis_config.history_key(session_id)
    try:
        r = await get_redis()
        msg = ConversationMessage(role=role, content=content)
        await r.lpush(key, msg.model_dump_json())
        # 设置/刷新 TTL
        await r.expire(key, redis_config.SESSION_TTL_SECONDS)
        logger.debug(f"[short_term] 写入 Redis: {role}: {content[:30]}...")
    except Exception as e:
        logger.error(f"[short_term] 写入 Redis 历史失败: {e}")
