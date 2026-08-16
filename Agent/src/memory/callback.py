"""
婉情AI - Java 后端回调模块 (Python → Java → MySQL)
=====================================================
架构约定：Python AI 服务不直连 MySQL，由 Java 层负责落库。

本模块负责：
  1. 将每轮对话的 session_log JSON 通过 HTTP POST 回调 Java ConversationController
  2. 回调失败时仅记录警告，不阻塞主对话流程

数据流：
  log_session_node (Python)
    → export_session_log() 序列化
    → _call_java_callback() HTTP POST
    → ConversationController /internal/conversation/log
    → SessionLogMapper.insert() → MySQL session_logs

参考文档：context-docs/03-memory-system/02.md
"""

import asyncio
from typing import Any

import httpx

from config import java_callback_config
from src.utils.logger import logger


async def call_java_conversation_log(session_log: dict[str, Any]) -> bool:
    """
    回调 Java 后端写入会话日志。

    Args:
        session_log: export_session_log() 导出的结构化会话日志

    Returns:
        True = 成功（HTTP 2xx），False = 失败
    """
    url = (
        java_callback_config.BASE_URL.rstrip("/")
        + java_callback_config.CONVERSATION_LOG_PATH
    )

    try:
        async with httpx.AsyncClient(timeout=java_callback_config.TIMEOUT) as client:
            response = await client.post(url, json=session_log)

            if response.status_code < 400:
                logger.debug(
                    f"[callback] 会话日志写入成功: session={session_log.get('session_id')}, "
                    f"action={session_log.get('intervention_decision', {}).get('suggested_action', '?')}"
                )
                return True
            else:
                logger.warning(
                    f"[callback] 会话日志写入失败 HTTP {response.status_code}: "
                    f"session={session_log.get('session_id')}, "
                    f"body={response.text[:200]}"
                )
                return False

    except httpx.TimeoutException:
        logger.warning(
            f"[callback] 回调 Java 超时 ({java_callback_config.TIMEOUT}s): "
            f"session={session_log.get('session_id')}"
        )
        return False
    except Exception as e:
        logger.warning(
            f"[callback] 回调 Java 异常: session={session_log.get('session_id')}, "
            f"error={e}"
        )
        return False
