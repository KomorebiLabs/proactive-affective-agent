"""
婉情AI - Redis 共享连接单例
=============================
职责：提供全局唯一的 aioredis 连接实例，供 Agent 各模块复用。

使用方式：
    from src.utils.redis_client import get_redis

依赖：
 - redis（同步） / redis.asyncio（异步）
"""

import redis.asyncio as aioredis
from typing import Optional

from config import redis_config
from src.utils.logger import logger

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """
    获取全局唯一的异步 Redis 连接（延迟初始化）。
    复用一个连接实例，避免每次请求都新建连接。
    """
    global _redis
    if _redis is None:
        password_part = f":{redis_config.PASSWORD}@" if redis_config.PASSWORD else ""
        url = f"redis://{password_part}{redis_config.HOST}:{redis_config.PORT}/{redis_config.DB}"
        logger.info(f"[redis_client] 初始化 Redis 连接：{redis_config.HOST}:{redis_config.PORT}/{redis_config.DB}")
        _redis = aioredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=redis_config.DECODE_RESPONSES
        )
    return _redis
