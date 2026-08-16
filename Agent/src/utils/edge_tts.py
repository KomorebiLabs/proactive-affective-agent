"""
Edge TTS 流式语音合成模块
==========================

使用 Microsoft Edge TTS API 实现流式语音合成。
完全免费、低延迟、支持中文。

使用方式：
    from src.utils.edge_tts import synthesize_stream
    await synthesize_stream("你好", "zh-CN-XiaoxiaoNeural", callback)

音频格式：MP3
"""

import asyncio
import edge_tts
import time
from typing import Optional

from src.utils.logger import logger


# 中文最佳音色列表
CHINESE_VOICES = {
    "xiaoxiao": "zh-CN-XiaoxiaoNeural",   # 晓晓，年轻女声
    "xiaoyi": "zh-CN-XiaoyiNeural",       # 小艺，温柔女声
    "yunxi": "zh-CN-YunxiNeural",         # 云希，活泼男声
    "yunyang": "zh-CN-YunyangNeural",     # 云扬，专业男声
    "yaoyao": "zh-CN-YaoyaoNeural",       # 瑶瑶，少女声音
    "jially": "zh-CN-JiaLyNeural",        # 加莉，成年女声
}

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"


async def synthesize_stream(
    text: str,
    voice: str = DEFAULT_VOICE,
    callback=None,
    on_start: Optional[callable] = None,
    on_complete: Optional[callable] = None,
    on_error: Optional[callable] = None,
):
    """
    Edge TTS 流式合成。

    Args:
        text: 待合成的文本
        voice: 音色名称，默认 zh-CN-XiaoxiaoNeural
        callback: 异步回调函数，收到每个音频块时调用 callback(chunk: bytes)
        on_start: 开始合成时的回调
        on_complete: 合成完成时的回调
        on_error: 错误时的回调
    """
    if not text or not text.strip():
        logger.warning("[EdgeTTS] 文本为空，跳过")
        return

    start_time = time.time()
    logger.info(f"[EdgeTTS] 开始流式合成: {text[:30]}... (voice={voice})")

    try:
        if on_start:
            await asyncio.coroutine(on_start)() if asyncio.iscoroutinefunction(on_start) else on_start()

        communicate = edge_tts.Communicate(text, voice)
        chunk_count = 0
        total_bytes = 0

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunk_count += 1
                total_bytes += len(chunk["data"])

                if callback:
                    await callback(chunk["data"])

        elapsed = time.time() - start_time
        logger.info(
            f"[EdgeTTS] 流式合成完成: {chunk_count} chunks, {total_bytes} bytes, "
            f"耗时 {elapsed:.2f}s"
        )

        if on_complete:
            await asyncio.coroutine(on_complete)() if asyncio.iscoroutinefunction(on_complete) else on_complete()

    except Exception as e:
        logger.error(f"[EdgeTTS] 流式合成异常: {e}")
        if on_error:
            await asyncio.coroutine(on_error)(str(e)) if asyncio.iscoroutinefunction(on_error) else on_error(e)
        raise


async def synthesize_file(text: str, voice: str, output_path: str) -> bool:
    """
    将文本合成音频并保存到文件。

    Args:
        text: 待合成的文本
        voice: 音色名称
        output_path: 输出文件路径

    Returns:
        bool: 是否成功
    """
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        logger.info(f"[EdgeTTS] 音频已保存到: {output_path}")
        return True
    except Exception as e:
        logger.error(f"[EdgeTTS] 保存音频失败: {e}")
        return False


async def synthesize_sync(text: str, voice: str = DEFAULT_VOICE) -> bytes:
    """
    同步合成（等待完整音频后返回）。

    Args:
        text: 待合成的文本
        voice: 音色名称

    Returns:
        bytes: MP3 音频数据
    """
    communicate = edge_tts.Communicate(text, voice)
    audio_data = b""

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_data += chunk["data"]

    return audio_data


def get_available_voices() -> list:
    """
    获取所有可用的音色列表。
    返回包含音色信息的字典列表。
    """
    return CHINESE_VOICES