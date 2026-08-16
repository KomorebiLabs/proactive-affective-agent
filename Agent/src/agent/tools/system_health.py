from __future__ import annotations

"""
婉情AI - 系统健康状态检查
============================
在 LLM 调用前，执行真实的多层健康检查，将验证后的系统状态注入 AgentState，
供 Prompt 引用，从而防止 LLM 捏造系统状态信息（如"Java后端没启动"等幻觉）。

检查项目：
  1. Java 后端 (8080) 是否在线
  2. 感知微服务 (8000) 是否在线
  3. Redis 是否可连接
  4. 感知模型是否已加载（通过检查感知微服务的模型状态）

设计原则：
  - 健康检查结果存入 AgentState，供所有节点使用
  - 状态为确定性事实（非 LLM 推断），直接注入 Prompt 的 system_facts 字段
"""

import asyncio
import json
import time
from typing import Any

import redis.asyncio as aioredis

from config import redis_config
from src.utils.logger import logger

# Java 后端地址（Python Agent 通过此地址检查 Java 是否在线）
_JAVA_BACKEND_URL = "http://localhost:8080/health"
_PERCEPTION_SERVICE_URL = "http://localhost:8000/health"


# ==============================================================================
# 健康状态数据模型
# ==============================================================================

class SystemHealthStatus:
    """系统各组件的健康状态（确定性事实，非 LLM 推断）"""

    def __init__(
        self,
        java_backend_online: bool = False,
        perception_service_online: bool = False,
        redis_connected: bool = False,
        emotion_model_loaded: bool = False,
        has_realtime_perception: bool = False,
        details: dict[str, Any] | None = None,
    ):
        self.java_backend_online = java_backend_online
        self.perception_service_online = perception_service_online
        self.redis_connected = redis_connected
        self.emotion_model_loaded = emotion_model_loaded
        self.has_realtime_perception = has_realtime_perception
        self.details = details or {}

    def is_fully_healthy(self) -> bool:
        """所有核心依赖是否就绪"""
        return self.java_backend_online and self.redis_connected

    def to_dict(self) -> dict[str, Any]:
        return {
            "java_backend_online": self.java_backend_online,
            "perception_service_online": self.perception_service_online,
            "redis_connected": self.redis_connected,
            "emotion_model_loaded": self.emotion_model_loaded,
            "has_realtime_perception": self.has_realtime_perception,
            "details": self.details,
        }

    def to_fact_string(self) -> str:
        """
        将健康状态转换为自然语言描述，供 Prompt 直接引用。
        格式：每项一行，前缀 ✅(正常) / ❌(异常) / ⚠️(警告)
        """
        lines = ["【系统状态确认】"]
        lines.append(f"  Java后端(8080): {'✅ 在线' if self.java_backend_online else '❌ 不在线'}")
        lines.append(f"  感知服务(8000): {'✅ 在线' if self.perception_service_online else '❌ 不在线'}")
        lines.append(f"  Redis连接: {'✅ 正常' if self.redis_connected else '❌ 失败'}")
        lines.append(f"  情绪模型: {'✅ 已加载' if self.emotion_model_loaded else '⚠️ 未加载，使用规则兜底'}")
        lines.append(f"  实时感知数据: {'✅ 有数据' if self.has_realtime_perception else '⚠️ 无数据'}")
        return "\n".join(lines)


# ==============================================================================
# HTTP 健康检查（异步，3秒超时）
# ==============================================================================

async def _check_http_health(url: str, name: str) -> bool:
    """检查指定 URL 的 HTTP 健康状态"""
    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "Wanqing-HealthCheck/1.0")
        with urllib.request.urlopen(req, timeout=3) as resp:
            status = resp.status
            if status == 200:
                logger.debug(f"[SystemHealth] {name} 在线: {url}")
                return True
            logger.warning(f"[SystemHealth] {name} 异常响应: HTTP {status}")
            return False
    except Exception as e:
        logger.debug(f"[SystemHealth] {name} 检查失败: {e}")
        return False


# ==============================================================================
# Redis 连接检查
# ==============================================================================

async def _check_redis() -> bool:
    """检查 Redis 是否可连接"""
    try:
        r = aioredis.Redis(
            host=redis_config.HOST,
            port=redis_config.PORT,
            db=redis_config.DB,
            password=redis_config.PASSWORD,
            decode_responses=True,
            socket_timeout=3,
            socket_connect_timeout=3,
        )
        await r.ping()
        await r.aclose()
        logger.debug("[SystemHealth] Redis 连接正常")
        return True
    except Exception as e:
        logger.debug(f"[SystemHealth] Redis 连接失败: {e}")
        return False


# ==============================================================================
# 感知微服务模型状态检查
# ==============================================================================

async def _check_emotion_model_status() -> tuple[bool, bool]:
    """
    检查感知微服务是否在线，以及情绪模型是否已加载。

    Returns:
        (perception_service_online, emotion_model_loaded)
    """
    perception_online = await _check_http_health(_PERCEPTION_SERVICE_URL, "感知服务")
    model_loaded = False

    if perception_online:
        try:
            import urllib.request
            req = urllib.request.Request(
                "http://localhost:8000/model_status",
                method="GET",
            )
            req.add_header("User-Agent", "Wanqing-HealthCheck/1.0")
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read())
                    model_loaded = data.get("model_loaded", False)
        except Exception:
            # model_status 端点可能不存在，此时无法确认模型状态，保守假设未加载
            model_loaded = False

    return perception_online, model_loaded


# ==============================================================================
# 实时感知数据检查
# ==============================================================================

async def _check_realtime_perception(session_id: str) -> bool:
    """检查 Redis 中是否存在该 session 的实时感知数据"""
    try:
        r = aioredis.Redis(
            host=redis_config.HOST,
            port=redis_config.PORT,
            db=redis_config.DB,
            password=redis_config.PASSWORD,
            decode_responses=True,
            socket_timeout=3,
            socket_connect_timeout=3,
        )
        key = redis_config.perception_key(session_id)
        raw = await r.get(key)
        await r.aclose()
        return raw is not None
    except Exception:
        return False


# ==============================================================================
# 核心检查函数（供 LangGraph 节点调用）
# ==============================================================================

async def check_system_health(session_id: str = "unknown") -> SystemHealthStatus:
    """
    执行完整的多层系统健康检查。

    此函数应在 LangGraph 执行前调用，结果存入 AgentState.system_health，
    供后续节点的 Prompt 引用，防止 LLM 在回复中捏造系统状态。

    Args:
        session_id: 当前会话ID，用于检查该 session 的感知数据是否存在

    Returns:
        SystemHealthStatus — 包含各组件状态的对象
    """
    logger.info(f"[SystemHealth] === 开始系统健康检查: session={session_id} ===")

    # 并发执行所有检查
    java_task = _check_http_health(_JAVA_BACKEND_URL, "Java后端")
    redis_task = _check_redis()
    perception_task = _check_emotion_model_status()
    realtime_task = _check_realtime_perception(session_id)

    java_online, redis_ok, (perception_online, model_loaded), has_realtime = await asyncio.gather(
        java_task, redis_task, perception_task, realtime_task
    )

    status = SystemHealthStatus(
        java_backend_online=java_online,
        perception_service_online=perception_online,
        redis_connected=redis_ok,
        emotion_model_loaded=model_loaded,
        has_realtime_perception=has_realtime,
        details={
            "checked_at": int(time.time() * 1000),
            "java_backend_url": _JAVA_BACKEND_URL,
            "perception_service_url": _PERCEPTION_SERVICE_URL,
        },
    )

    logger.info(
        f"[SystemHealth] === 检查完成 === "
        f"Java={'✅' if java_online else '❌'} "
        f"Perception={'✅' if perception_online else '❌'} "
        f"Redis={'✅' if redis_ok else '❌'} "
        f"Model={'✅' if model_loaded else '⚠️'} "
        f"Realtime={'✅' if has_realtime else '⚠️'}"
    )

    return status
