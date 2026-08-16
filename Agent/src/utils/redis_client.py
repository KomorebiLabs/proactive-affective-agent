"""
婉情AI - Redis 共享连接单例（全 Agent 唯一实现）
====================================================
职责：提供全局唯一的异步 Redis 连接池，供 Agent 各模块复用。
memory/short_term、emotion/perception 等模块一律从这里导入，
禁止再各自维护 ConnectionPool 副本。

使用方式：
    from src.utils.redis_client import get_redis

依赖：
 - redis.asyncio（异步）
"""

import redis.asyncio as aioredis
from typing import Optional

from config import redis_config
from src.utils.logger import logger

_redis: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """
    获取全局唯一的异步 Redis 客户端（延迟初始化，带界连接池）。
    """
    global _redis
    if _redis is None:
        pool = aioredis.ConnectionPool(
            host=redis_config.HOST,
            port=redis_config.PORT,
            db=redis_config.DB,
            password=redis_config.PASSWORD,
            decode_responses=redis_config.DECODE_RESPONSES,
            max_connections=20,
        )
        logger.info(f"[redis_client] 初始化 Redis 连接池：{redis_config.HOST}:{redis_config.PORT}/{redis_config.DB}")
        _redis = aioredis.Redis(connection_pool=pool)
    return _redis
