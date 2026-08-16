"""
婉情AI - TTS 语音合成模块
=========================
职责：调用 TTS API 生成语音，并通过 WebSocket 发送到前端播放。

支持多种 TTS 提供商：
- edge: Microsoft Edge TTS（免费、流式、推荐）
- volcengine: 火山引擎豆包语音（流式 WebSocket）
- dashscope: 阿里 DashScope（流式回调）

使用方式：
    from src.utils.tts import speak_text
    await speak_text("你好，我是婉情")
"""

import asyncio
import base64
import json
import queue
import threading
import time
from typing import Optional

from config import audio_config
from src.utils.logger import logger
from src.utils import websocket_client

# TTS 提供商路由
_TTS_PROVIDER = audio_config.TTS_PROVIDER.lower()
logger.info(f"[TTS] 使用 TTS 提供商: {_TTS_PROVIDER}")

if _TTS_PROVIDER == "edge":
    from src.utils.edge_tts import synthesize_stream, DEFAULT_VOICE
    _DASHSCOPE_MODE = False
elif _TTS_PROVIDER == "volcengine":
    try:
        from src.utils.volcengine_tts import speak_text as _volc_speak
        _DASHSCOPE_MODE = False
    except ImportError:
        logger.warning("[TTS] src/utils/volcengine_tts.py 不存在，volcengine 分支降级为 Edge TTS（补齐该模块后方可启用）")
        _TTS_PROVIDER = "edge"
        from src.utils.edge_tts import synthesize_stream, DEFAULT_VOICE
        _DASHSCOPE_MODE = False
elif _TTS_PROVIDER == "dashscope":
    import dashscope
    from dashscope.audio.tts_v2 import SpeechSynthesizer, ResultCallback
    dashscope.api_key = __import__("os").getenv("DASHSCOPE_API_KEY") or __import__("os").getenv("QWEN_API_KEY", "")
    _DASHSCOPE_MODE = True
else:
    logger.warning(f"[TTS] 未知的 TTS 提供商 '{_TTS_PROVIDER}'，将使用 Edge TTS")
    _TTS_PROVIDER = "edge"
    from src.utils.edge_tts import synthesize_stream, DEFAULT_VOICE
    _DASHSCOPE_MODE = False

# TTS 并发控制：防止 API 限流
_tts_semaphore = asyncio.Semaphore(2)


if _DASHSCOPE_MODE:
    class StreamingTTSCallback(ResultCallback):
        """
        流式 TTS 回调（DASHSCOPE）：将实时返回的音频块通过队列发送给 WebSocket。
        """

        def __init__(self, audio_queue: queue.Queue, done_event: threading.Event):
            self.audio_queue = audio_queue
            self.done_event = done_event
            self.first_chunk_received = False

        def on_open(self) -> None:
            logger.debug("[TTS Callback] WebSocket 连接已打开")

        def on_data(self, data: bytes) -> None:
            """实时接收音频数据，立即放入队列"""
            if not self.first_chunk_received:
                logger.info(f"[TTS Callback] 收到首个音频块: {len(data)} bytes")
                self.first_chunk_received = True
            self.audio_queue.put(data)

        def on_complete(self) -> None:
            logger.debug("[TTS Callback] 合成完成")
            self.audio_queue.put(None)
            self.done_event.set()

        def on_error(self, message) -> None:
            logger.error(f"[TTS Callback] 错误: {message}")
            self.audio_queue.put(None)
            self.done_event.set()

        def on_close(self) -> None:
            logger.debug("[TTS Callback] WebSocket 连接关闭")


async def speak_text(text: str, voice: Optional[str] = None, max_retries: int = 2) -> bool:
    """
    将文本转换为语音并通过 WebSocket 发送到前端。

    Args:
        text: 要转换的文本
        voice: 可选的音色名称，默认使用 audio_config.TTS_VOICE
        max_retries: 最大重试次数（防止 API 限流）

    Returns:
        bool: 是否成功发送
    """
    if not text or not text.strip():
        logger.warning("[TTS] 文本为空，跳过")
        return False

    if _TTS_PROVIDER == "edge":
        return await _speak_edge(text, voice, max_retries)
    elif _TTS_PROVIDER == "volcengine":
        return await _speak_volcengine(text, voice, max_retries)
    else:
        return await _speak_dashscope(text, voice, max_retries)


async def _speak_edge(text: str, voice: Optional[str], max_retries: int) -> bool:
    """
    Edge TTS 流式合成路由。
    使用 edge-tts 库，支持流式输出、低延迟、免费。
    """
    from src.utils.edge_tts import DEFAULT_VOICE

    # 确定音色：用户指定 > 配置 > 默认
    voice_name = voice or getattr(audio_config, "EDGE_TTS_VOICE", None) or DEFAULT_VOICE

    logger.info(f"[TTS] Edge TTS 流式合成: {text[:30]}... (voice={voice_name})")

    last_error = None

    for attempt in range(max_retries + 1):
        try:
            success = await _stream_speak_and_send_edge(text, voice_name)
            if success:
                logger.info(f"[TTS] Edge TTS 语音合成并发送成功 (attempt={attempt + 1})")
                return True
            else:
                last_error = "流式发送失败"
                logger.warning(f"[TTS] Edge TTS 流式发送失败 (attempt={attempt + 1})")

        except asyncio.TimeoutError:
            last_error = "超时"
            logger.warning(f"[TTS] Edge TTS 第 {attempt + 1} 次尝试超时（30秒）")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[TTS] Edge TTS 尝试 {attempt + 1} 失败: {e}")

        if attempt < max_retries:
            await asyncio.sleep(0.5)

    logger.error(f"[TTS] Edge TTS 语音合成最终失败: {last_error}")
    return False


async def _stream_speak_and_send_edge(text: str, voice: str) -> bool:
    """
    Edge TTS 流式合成并发送。

    音频块通过 TTS 专用 WebSocket 连接实时推送到前端。
    核心：用 asyncio.Queue 替代阻塞 queue.Queue，
    用 async for 正确驱动 edge-tts 的 async_generator。
    """
    stream_id = f"edge_{int(time.time() * 1000)}"
    logger.debug(f"[TTS] Edge TTS 流式合成开始 (stream_id={stream_id})")

    try:
        conn = await websocket_client.get_tts_connection()
        if not conn:
            logger.error("[TTS] 无法获取 TTS 专用连接")
            return False

        audio_q: asyncio.Queue = asyncio.Queue()
        shared_state = {"total_sent": 0, "chunk_count": 0, "stream_started": False}
        sender_done = asyncio.Event()
        sender_error: dict = {}

        async def audio_sender():
            """异步发送音频块"""
            try:
                while True:
                    try:
                        audio_frame = await asyncio.wait_for(audio_q.get(), timeout=5.0)
                    except asyncio.TimeoutError:
                        if audio_q.empty():
                            break
                        continue

                    if audio_frame is None:
                        break

                    audio_b64 = base64.b64encode(audio_frame).decode("utf-8")
                    is_first = not shared_state["stream_started"]

                    message = {
                        "type": "voice_stream",
                        "stream_id": stream_id,
                        "data": audio_b64,
                        "is_first": is_first,
                        "is_last": False,
                        "chunk_index": shared_state["chunk_count"],
                        "provider": "edge",
                    }

                    try:
                        await asyncio.wait_for(conn.send(json.dumps(message)), timeout=5.0)
                    except Exception as e:
                        sender_error["err"] = e
                        logger.error(f"[TTS] 发送音频块失败: {e}")
                        break

                    if is_first:
                        shared_state["stream_started"] = True
                        logger.info(
                            f"[TTS] Edge TTS 首个音频块已发送: stream_id={stream_id}, "
                            f"size={len(audio_frame)}, time={time.time():.3f}"
                        )

                    shared_state["total_sent"] += len(audio_frame)
                    shared_state["chunk_count"] += 1

                # 发送结束标记
                end_message = {
                    "type": "voice_stream_end",
                    "stream_id": stream_id,
                    "total_chunks": shared_state["chunk_count"],
                    "total_bytes": shared_state["total_sent"],
                }
                try:
                    await asyncio.wait_for(conn.send(json.dumps(end_message)), timeout=5.0)
                    logger.info(
                        f"[TTS] Edge TTS 流式发送完成: {shared_state['chunk_count']} chunks, "
                        f"{shared_state['total_sent']} bytes"
                    )
                except Exception as e:
                    logger.warning(f"[TTS] 发送结束标记失败: {e}")
            except Exception as e:
                sender_error["err"] = e
                logger.error(f"[TTS] audio_sender 异常: {e}")
            finally:
                sender_done.set()

        async def audio_producer():
            """在独立线程中驱动 edge-tts（避免阻塞主事件循环）"""
            def _run():
                # 在同步线程中创建事件循环，驱动 async edge-tts
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    async def on_chunk(chunk: bytes):
                        audio_q.put_nowait(chunk)
                    loop.run_until_complete(synthesize_stream(text, voice, callback=on_chunk))
                finally:
                    audio_q.put_nowait(None)
                    loop.close()

            try:
                await asyncio.get_running_loop().run_in_executor(None, _run)
            except Exception as e:
                logger.error(f"[TTS] audio_producer 异常: {e}")
                audio_q.put_nowait(None)

        # 两个协程并发运行：producer 在线程中填充队列，sender 实时取队列发送
        await asyncio.gather(audio_producer(), audio_sender())

        if shared_state["chunk_count"] > 0:
            return True
        else:
            logger.warning("[TTS] Edge TTS 流式合成无输出")
            return False

    except Exception as e:
        logger.error(f"[TTS] Edge TTS 流式合成异常: {e}")
        return False


def _synthesize_sync(text: str, model: str, voice: str) -> Optional[bytes]:
    """
    同步 TTS 合成（供 run_in_executor 调用）
    """
    try:
        synthesizer = SpeechSynthesizer(model=model, voice=voice)
        audio_data = synthesizer.call(text)
        return audio_data
    except Exception as e:
        logger.error(f"[TTS] DashScope 底层错误: {e}")
        return None


async def _speak_volcengine(text: str, voice: Optional[str], max_retries: int) -> bool:
    """
    火山引擎 TTS 路由。
    """
    voice_name = voice or audio_config.TTS_VOICE
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            success = await _volc_speak(text, voice=voice_name)
            if success:
                logger.info(f"[TTS] 火山引擎语音合成成功 (attempt={attempt + 1})")
                return True
            else:
                last_error = "流式发送失败"
                logger.warning(f"[TTS] 火山引擎流式发送失败 (attempt={attempt + 1})")
        except asyncio.TimeoutError:
            last_error = "超时"
            logger.warning(f"[TTS] 火山引擎第 {attempt + 1} 次尝试超时（30秒）")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[TTS] 火山引擎尝试 {attempt + 1} 失败: {e}")

        if attempt < max_retries:
            await asyncio.sleep(0.5)

    logger.error(f"[TTS] 火山引擎语音合成最终失败: {last_error}")
    return False


async def _speak_dashscope(text: str, voice: Optional[str], max_retries: int) -> bool:
    """
    DashScope TTS 路由。
    """
    voice_name = voice or audio_config.TTS_VOICE
    model_name = audio_config.TTS_MODEL

    logger.info(f"[TTS] 开始流式合成语音: {text[:30]}... (voice={voice_name})")

    last_error = None

    for attempt in range(max_retries + 1):
        try:
            async with _tts_semaphore:
                success = await _stream_speak_and_send_dashscope(text, model_name, voice_name)

            if success:
                logger.info(f"[TTS] DashScope 语音合成并发送成功 (attempt={attempt + 1})")
                return True
            else:
                last_error = "流式发送失败"
                logger.warning(f"[TTS] DashScope 流式发送失败 (attempt={attempt + 1})")

        except asyncio.TimeoutError:
            last_error = "超时"
            logger.warning(f"[TTS] DashScope 第 {attempt + 1} 次尝试超时（30秒）")
        except Exception as e:
            last_error = str(e)
            logger.warning(f"[TTS] DashScope 尝试 {attempt + 1} 失败: {e}")

        if attempt < max_retries:
            await asyncio.sleep(0.5)

    logger.error(f"[TTS] DashScope 语音合成最终失败: {last_error}")
    return False


async def _stream_speak_and_send_dashscope(text: str, model: str, voice: str) -> bool:
    """
    DashScope 流式 TTS：使用 ResultCallback 实时接收音频块并发送。

    【TTS重构】使用 TTS 专用连接，不与视频帧共享带宽。
    """
    stream_id = f"{int(time.time() * 1000)}"
    logger.debug(f"[TTS] DashScope 流式合成开始 (stream_id={stream_id})")

    try:
        # 【TTS重构】获取 TTS 专用连接
        conn = await websocket_client.get_tts_connection()
        if not conn:
            logger.error("[TTS] 无法获取 TTS 专用连接")
            return False

        audio_queue: queue.Queue = queue.Queue()
        done_event = threading.Event()
        shared_state = {"total_sent": 0, "chunk_count": 0}
        first_chunk_sent = [False]
        send_done = threading.Event()

        async def audio_sender():
            """异步发送音频块（边接收边发送）"""
            try:
                while not done_event.is_set() or not audio_queue.empty():
                    try:
                        audio_frame = audio_queue.get(timeout=0.5)
                        if audio_frame is None:
                            break

                        audio_b64 = base64.b64encode(audio_frame).decode("utf-8")
                        is_first = not first_chunk_sent[0]
                        message = {
                            "type": "voice_stream",
                            "stream_id": stream_id,
                            "data": audio_b64,
                            "is_first": is_first,
                            "is_last": False,
                            "chunk_index": shared_state["chunk_count"]
                        }
                        
                        # 【TTS重构】使用 await 等待发送完成
                        await asyncio.wait_for(conn.send(json.dumps(message)), timeout=5.0)

                        if is_first:
                            first_chunk_sent[0] = True
                            logger.info(f"[TTS] DashScope 首个音频块已发送: stream_id={stream_id}, size={len(audio_frame)}, time={time.time():.3f}")

                        shared_state["total_sent"] += len(audio_frame)
                        shared_state["chunk_count"] += 1

                    except queue.Empty:
                        continue
                    except asyncio.TimeoutError:
                        logger.warning("[TTS] DashScope 发送超时")
                        break
                    except Exception as e:
                        logger.error(f"[TTS] 发送音频块失败: {e}")
                        break

                end_message = {
                    "type": "voice_stream_end",
                    "stream_id": stream_id,
                    "total_chunks": shared_state["chunk_count"],
                    "total_bytes": shared_state["total_sent"]
                }
                try:
                    await asyncio.wait_for(conn.send(json.dumps(end_message)), timeout=5.0)
                    logger.info(f"[TTS] DashScope 流式发送完成: {shared_state['chunk_count']} chunks, {shared_state['total_sent']} bytes")
                except Exception as e:
                    logger.warning(f"[TTS] 发送结束标记失败: {e}")
            finally:
                send_done.set()

        def audio_generator():
            try:
                callback = StreamingTTSCallback(audio_queue, done_event)
                synthesizer = SpeechSynthesizer(model=model, voice=voice, callback=callback)
                synthesizer.call(text)
            except Exception as e:
                logger.error(f"[TTS] 音频生成异常: {e}")
                done_event.set()
                audio_queue.put(None)

        sender_task = asyncio.create_task(audio_sender())
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, audio_generator)
        
        # 等待发送完成
        send_done.wait(timeout=60)
        if not sender_task.done():
            sender_task.cancel()

        if shared_state["chunk_count"] > 0:
            return True
        else:
            logger.warning("[TTS] DashScope 流式合成无输出")
            return False

    except Exception as e:
        logger.error(f"[TTS] DashScope 流式合成异常: {e}")
        return False


async def speak_text_direct(text: str, websocket_manager, voice: Optional[str] = None) -> bool:
    """
    直接通过传入的 WebSocket manager 发送语音（备用方法）。

    Args:
        text: 要转换的文本
        websocket_manager: WebSocket 连接管理器
        voice: 可选的音色名称
    """
    if not text or not text.strip():
        return False

    voice_name = voice or audio_config.TTS_VOICE
    model_name = audio_config.TTS_MODEL

    logger.info(f"[TTS] 开始合成语音: {text[:30]}... (voice={voice_name})")

    try:
        loop = asyncio.get_event_loop()
        audio_data = await loop.run_in_executor(
            None, _synthesize_sync, text, model_name, voice_name
        )

        if not audio_data:
            logger.warning("[TTS] 合成返回空数据，跳过播放")
            return False

        audio_b64 = base64.b64encode(audio_data).decode("utf-8")
        audio_url = f"data:audio/mp3;base64,{audio_b64}"

        # 直接通过 WebSocket manager 广播
        if websocket_manager:
            await websocket_manager.broadcast({
                "type": "voice_play",
                "data": audio_url
            })
            logger.info("[TTS] 语音数据已发送")
            return True
        else:
            logger.warning("[TTS] WebSocket manager 为空，无法发送")
            return False

    except Exception as e:
        logger.error(f"[TTS] 语音合成失败: {e}")
        return False
