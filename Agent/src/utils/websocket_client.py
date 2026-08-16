"""
婉情AI - WebSocket 广播客户端
============================
职责：Agent (8001) 通过此模块向感知服务 (8000) 的 WebSocket 广播消息，
     实现 TTS 语音播放等功能。

使用方式：
    from src.utils.websocket_client import broadcast_voice, broadcast_message
    await broadcast_voice("data:audio/mp3;base64,...")

【TTS重构】新增 TTS 专用连接池，与普通连接分离，避免视频帧抢占 TTS 带宽。
"""

import asyncio
import json
import logging
from typing import Optional

import websockets

from config import perception_config
from src.utils.logger import logger

# WebSocket 连接地址（感知服务 8000）
_PERCEPTION_WS_URL = f"ws://localhost:{perception_config.PERCEPTION_SERVICE_PORT}/ws"

# 连接池（复用连接，避免频繁建立断开）
_connections: list[websockets.WebSocketClientProtocol] = []

# 【TTS重构】TTS 专用连接（独立于普通连接池）
_tts_connection: Optional[websockets.WebSocketClientProtocol] = None
_tts_lock = asyncio.Lock()

# 原子锁，防止多协程同时建立连接
_conn_lock = asyncio.Lock()


async def _ensure_connection_alive(conn: websockets.WebSocketClientProtocol) -> bool:
    """检查连接是否仍然活跃。"""
    try:
        if conn.open:
            return True
    except Exception:
        pass
    return False


async def _do_connect() -> Optional[websockets.WebSocketClientProtocol]:
    """实际建立 WebSocket 连接的内部函数。"""
    conn = await websockets.connect(
        _PERCEPTION_WS_URL,
        ping_interval=30,
        ping_timeout=10,
    )
    # 发送心跳，标识自己为 Agent 客户端
    await conn.send(json.dumps({"type": "agent_heartbeat"}))
    logger.info(f"[WebSocket Client] 已连接到感知服务: {_PERCEPTION_WS_URL}")
    return conn


async def get_connection(max_attempts: int = 3, retry_delay: float = 0.5) -> Optional[websockets.WebSocketClientProtocol]:
    """
    获取或建立 WebSocket 连接。
    连接会被缓存复用。
    连接断开时会自动重试重建。
    """
    global _connections

    last_error = None

    for attempt in range(max_attempts):
        # 并发保护：只允许一个协程建立连接
        async with _conn_lock:
            # 清理已断开的连接
            valid_connections = []
            for conn in _connections:
                if await _ensure_connection_alive(conn):
                    valid_connections.append(conn)
                else:
                    try:
                        await conn.close()
                    except Exception:
                        pass
            _connections = valid_connections

            # 尝试复用已有连接
            for conn in _connections:
                if await _ensure_connection_alive(conn):
                    return conn

            # 需要新建连接（加锁保护，防止多协程重复建立）
            try:
                conn = await _do_connect()
                _connections.append(conn)
                return conn
            except Exception as e:
                last_error = e
                _connections.clear()
                logger.warning(
                    f"[WebSocket Client] 连接失败 (attempt={attempt + 1}/{max_attempts}): {e}"
                )

        # 锁外等待后重试（让其他协程有机会参与）
        if attempt < max_attempts - 1:
            await asyncio.sleep(retry_delay)

    logger.warning(f"[WebSocket Client] 连接重试 {max_attempts} 次全部失败: {last_error}")
    return None


async def broadcast_message(msg_type: str, data: any) -> bool:
    """
    通过 WebSocket 广播消息到所有连接的客户端。

    Args:
        msg_type: 消息类型（如 "voice_play"）
        data: 消息数据

    Returns:
        bool: 是否成功发送
    """
    try:
        conn = await get_connection()
        if not conn:
            logger.warning("[WebSocket Client] 无法获取连接，广播失败")
            return False

        message = json.dumps({
            "type": msg_type,
            "data": data
        })
        await conn.send(message)
        logger.debug(f"[WebSocket Client] 广播成功: {msg_type}")
        return True

    except Exception as e:
        logger.warning(f"[WebSocket Client] 广播失败: {e}")
        # 连接可能已断开，清理并重试
        await close_all_connections()
        return False


async def broadcast_voice(audio_url: str) -> bool:
    """
    广播 TTS 语音数据到前端播放。

    Args:
        audio_url: Base64 编码的音频数据 URL

    Returns:
        bool: 是否成功发送
    """
    try:
        conn = await get_connection()
        if not conn:
            logger.error("[WebSocket Client] 无法获取连接，广播失败")
            return False

        message = json.dumps({
            "type": "voice_play",
            "data": audio_url
        })
        await conn.send(message)
        logger.info(f"[WebSocket Client] TTS 音频已发送 (长度: {len(audio_url)} bytes)")
        return True

    except Exception as e:
        logger.error(f"[WebSocket Client] 广播失败: {e}")
        # 连接可能已断开，清理并重试一次
        await close_all_connections()
        return False


async def close_all_connections() -> None:
    """关闭所有 WebSocket 连接"""
    global _connections
    async with _conn_lock:
        for conn in _connections:
            try:
                await conn.close()
            except Exception:
                pass
        _connections.clear()
        logger.info("[WebSocket Client] 所有连接已关闭")


async def cleanup_stale_connections() -> None:
    """清理已断开的连接"""
    global _connections
    async with _conn_lock:
        stale = []
        for conn in _connections:
            try:
                if not conn.open:
                    stale.append(conn)
            except Exception:
                stale.append(conn)
        for conn in stale:
            try:
                _connections.remove(conn)
            except ValueError:
                pass


# ============================================================
# 【TTS重构】TTS 专用连接
# ============================================================

async def get_tts_connection(max_attempts: int = 3, retry_delay: float = 0.5) -> Optional[websockets.WebSocketClientProtocol]:
    """
    获取 TTS 专用连接（独立于普通连接池）。
    
    TTS 连接使用独立的通道，不与视频帧共享带宽，
    确保 TTS 音频块的延迟 < 1秒。

    Returns:
        WebSocket 连接或 None
    """
    global _tts_connection

    last_error = None

    for attempt in range(max_attempts):
        async with _tts_lock:
            # 检查现有连接是否有效
            if _tts_connection is not None:
                try:
                    if _tts_connection.open:
                        return _tts_connection
                except Exception:
                    pass
            
            # 需要新建 TTS 专用连接
            try:
                logger.info(f"[WebSocket Client] 建立 TTS 专用连接 (attempt={attempt + 1})")
                _tts_connection = await websockets.connect(
                    _PERCEPTION_WS_URL,
                    ping_interval=30,
                    ping_timeout=10,
                    max_size=50 * 1024 * 1024,  # 50MB，支持大音频块
                    max_queue=256,
                )
                # 发送 TTS 通道标识
                await _tts_connection.send(json.dumps({"type": "tts_stream_start"}))
                logger.info("[WebSocket Client] TTS 专用通道已建立")
                return _tts_connection
            except Exception as e:
                last_error = e
                _tts_connection = None
                logger.warning(
                    f"[WebSocket Client] TTS 连接失败 (attempt={attempt + 1}/{max_attempts}): {e}"
                )

        # 锁外等待后重试
        if attempt < max_attempts - 1:
            await asyncio.sleep(retry_delay)

    logger.error(f"[WebSocket Client] TTS 连接重试 {max_attempts} 次全部失败: {last_error}")
    return None


async def close_tts_connection() -> None:
    """关闭 TTS 专用连接"""
    global _tts_connection
    async with _tts_lock:
        if _tts_connection is not None:
            try:
                await _tts_connection.close()
                logger.info("[WebSocket Client] TTS 专用连接已关闭")
            except Exception:
                pass
            _tts_connection = None

