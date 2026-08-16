# ==============================================================================
# Wanqing Backend - openSMILE 音频特征提取模块
# ==============================================================================
# 职责：
#   1. 从 PyAudio 音频流中实时提取音频特征（eGeMAPS 88维特征集）
#   2. 计算基频 F0、响度 Loudness、MFCC系数
#   3. 独立后台线程运行，以 2Hz 频率输出特征
#   4. 与现有的 VAD (VoiceActivityDetector) 共享 PyAudio 麦克风资源
#
# 性能说明：
#   openSMILE 的 eGeMAPS 特征提取需要整段音频信号（非单帧），
#   因此采用"滚动缓冲区 + 固定窗口步进"策略：
#     - 窗口长度：3秒
#     - 步进间隔：0.5秒（对应 2Hz 输出频率）
#
# openSMILE eGeMAPS 特征集说明：
#   - F0semitoneFrom27Hz：基频（半音阶表示，归一化音调）
#   - loudnessPeaksEqRng：响度峰值
#   - MFCC[1-14]：梅尔频率倒谱系数
#   - pcm_loudness_sma：整体响度
#   - voicingFinalUnclipped：浊音/清音概率（用于 VAD）
# ==============================================================================

from __future__ import annotations

import io
import struct
import threading
import time
import wave
from collections import deque
from typing import Any

import numpy as np
import pyaudio

from ai_assistant.utils import config


# ==============================================================================
# openSMILE 特征提取器（延迟初始化）
# ==============================================================================

_smile = None  # openSMILE 实例，全局单例


def _get_smile():
    """延迟初始化 openSMILE（全局单例）"""
    global _smile
    if _smile is None:
        try:
            import opensmile

            _smile = opensmile.Smile(
                feature_set=opensmile.FeatureSet.eGeMAPSv02,
                feature_level=opensmile.FeatureLevel.LowLevelDescriptors,
            )
            print("[AudioFeature] openSMILE eGeMAPSv02 初始化完成")
        except Exception as e:
            print(f"[AudioFeature] openSMILE 初始化失败: {e}")
            _smile = None
    return _smile


def _process_wav_buffer(
    audio_buffer: np.ndarray,
    sample_rate: int,
) -> dict[str, Any] | None:
    """
    将音频缓冲区转换为 WAV 格式，送入 openSMILE 提取特征。

    Args:
        audio_buffer: 原始 PCM 音频数据（float32, 范围 -1.0~1.0 或 int16）
        sample_rate: 采样率（Hz）

    Returns:
        包含提取特征的字典，或 None（提取失败时）
    """
    smile = _get_smile()
    if smile is None:
        return None

    try:
        # 将 numpy 数组转换为 WAV 格式的 bytes
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16
            wf.setframerate(sample_rate)
            # 转换为 int16
            if audio_buffer.dtype == np.float32 or audio_buffer.dtype == np.float64:
                audio_int16 = (audio_buffer * 32767.0).astype(np.int16)
            else:
                audio_int16 = audio_buffer.astype(np.int16)
            wf.writeframes(audio_int16.tobytes())

        wav_buffer.seek(0)

        # openSMILE 提取特征
        result = smile.process_file(wav_buffer)

        # 解析结果（DataFrame → dict）
        if result is None or result.empty:
            return None

        row = result.iloc[-1]  # 取窗口内最后一帧的统计值

        # 提取关键特征（与 Agent 期望的 AudioFeatures 对齐）
        features: dict[str, Any] = {}

        # F0（基频）：半音阶值 → 转换为 Hz
        try:
            f0_semitone = float(row.get("F0semitoneFrom27Hz", 0.0))
            # 转换公式：f = 27 * 2^(semitone/12)
            features["pitch"] = 27.0 * (2.0 ** (f0_semitone / 12.0)) if f0_semitone > 0 else 0.0
        except (ValueError, KeyError):
            features["pitch"] = 0.0

        # 响度
        try:
            loudness = float(row.get("pcm_loudness_sma", 0.0))
            # 归一化到 0~1（eGeMAPS 响度范围约 0~150）
            features["loudness"] = min(1.0, max(0.0, loudness / 150.0))
        except (ValueError, KeyError):
            features["loudness"] = 0.0

        # MFCC 系数（前13维）
        mfcc_list = []
        for i in range(1, 14):
            try:
                val = float(row.get(f"MFCC{i}_sma", 0.0))
            except (ValueError, KeyError):
                val = 0.0
            mfcc_list.append(round(val, 4))
        features["mfcc"] = mfcc_list

        # 浊音概率（用于 VAD）
        try:
            voicing = float(row.get("voicingFinalUnclipped", 0.0))
            features["voicing_prob"] = min(1.0, max(0.0, voicing))
        except (ValueError, KeyError):
            features["voicing_prob"] = 0.0

        return features

    except Exception as e:
        print(f"[AudioFeature] openSMILE 特征提取失败: {e}")
        return None


# ==============================================================================
# 音频特征提取器（独立后台线程）
# ==============================================================================

class AudioFeatureExtractor:
    """
    音频特征实时提取器。

    工作流程：
    1. 后台线程持续从 PyAudio 流读取音频数据块
    2. 存入滚动缓冲区（3秒窗口）
    3. 每 0.5 秒触发一次 openSMILE 特征提取
    4. 结果写入 self.latest_features（线程安全）

    使用方式：
        extractor = AudioFeatureExtractor()
        extractor.start()
        # 主循环中：
        features = extractor.get_latest()
        extractor.stop()
    """

    # 音频录制参数（与 audio_processing.py 保持一致）
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = config.AUDIO_RATE  # 16000 Hz
    CHUNK = config.AUDIO_CHUNK  # 1024 samples

    # 特征提取窗口参数
    WINDOW_SECONDS = 3.0  # 滚动窗口长度
    STEP_SECONDS = 0.5   # 步进间隔（2Hz）
    MIN_CHUNKS_FOR_WINDOW = int(WINDOW_SECONDS * RATE / CHUNK)

    def __init__(self):
        self._audio: pyaudio.PyAudio | None = None
        self._stream = None
        self._thread: threading.Thread | None = None
        self._running = False

        # 滚动缓冲区（存储 int16 PCM 数据）
        self._buffer: deque[np.ndarray] = deque(maxlen=self.MIN_CHUNKS_FOR_WINDOW)

        # 最新特征（线程安全）
        self._latest_lock = threading.Lock()
        self._latest_features: dict[str, Any] = {
            "pitch": 0.0,
            "loudness": 0.0,
            "mfcc": [0.0] * 13,
            "speaking": False,
            "voicing_prob": 0.0,
        }

        # VAD 状态
        self._vad_threshold = 0.3  # 浊音概率阈值

        # 统计
        self._frame_count = 0
        self._last_extract_time = 0.0

    # --------------------------------------------------------------------------
    # 外部调用接口
    # --------------------------------------------------------------------------

    def start(self) -> bool:
        """启动音频录制与特征提取线程"""
        if self._running:
            return True

        try:
            self._audio = pyaudio.PyAudio()
            self._stream = self._audio.open(
                format=self.FORMAT,
                channels=self.CHANNELS,
                rate=self.RATE,
                input=True,
                frames_per_buffer=self.CHUNK,
                start=False,  # 手动控制启动
            )
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            print("[AudioFeature] 音频特征提取器已启动")
            return True

        except Exception as e:
            print(f"[AudioFeature] 启动失败: {e}")
            self._running = False
            return False

    def stop(self) -> None:
        """安全停止音频录制线程"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass

        if self._audio:
            try:
                self._audio.terminate()
            except Exception:
                pass

        print("[AudioFeature] 音频特征提取器已停止")

    def get_latest(self) -> dict[str, Any]:
        """
        获取最新一帧音频特征（线程安全）。

        Returns:
            dict，包含：
              - pitch: float（基频 Hz）
              - loudness: float（响度，0~1）
              - mfcc: list[float]（13维 MFCC 系数）
              - speaking: bool（是否在说话）
              - voicing_prob: float（浊音概率，0~1）
        """
        with self._latest_lock:
            return dict(self._latest_features)

    def is_speaking(self) -> bool:
        """快速判断当前是否在说话（基于浊音概率）"""
        with self._latest_lock:
            return self._latest_features.get("speaking", False)

    def feed_audio_chunk(self, base64_data: str) -> bool:
        """
        接收前端 WebSocket 传来的音频 chunk，更新缓冲区。

        适用场景：前端麦克风采集 → WebSocket → 后端 → 此方法
        与 PyAudio 模式互斥，但可以同时工作（以先到的数据为准）。

        Args:
            base64_data: Base64 编码的 PCM16 单声道音频数据

        Returns:
            True 表示数据已接收并处理；False 表示解码失败或数据无效
        """
        try:
            import base64 as _b64
            raw_bytes = _b64.b64decode(base64_data)
            # 转换为 numpy float32 [-1.0, 1.0]
            samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            if samples.size == 0:
                return False
            self._buffer.append(samples)
            self._frame_count += 1

            # 触发特征提取（每当积累够 1 个窗口的数据）
            if len(self._buffer) >= self.MIN_CHUNKS_FOR_WINDOW // 2:
                self._extract_and_update()
                self._last_extract_time = time.time()

            return True
        except Exception as e:
            print(f"[AudioFeature] feed_audio_chunk 失败: {e}")
            return False

    # --------------------------------------------------------------------------
    # 内部线程
    # --------------------------------------------------------------------------

    def _run_loop(self) -> None:
        """后台录制线程主循环"""
        assert self._stream is not None

        self._stream.start_stream()

        while self._running:
            try:
                # 读取一帧音频
                data = self._stream.read(self.CHUNK, exception_on_overflow=False)

                # 转换为 numpy 数组
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                self._buffer.append(samples)
                self._frame_count += 1

                # 每 STEP_SECONDS 秒触发一次特征提取
                current_time = time.time()
                if current_time - self._last_extract_time >= self.WINDOW_SECONDS:
                    self._extract_and_update()
                    self._last_extract_time = current_time

                # 短暂让出 CPU
                time.sleep(0.01)

            except IOError as e:
                if e.errno == -9981:  # 输入溢出
                    continue
                print(f"[AudioFeature] 录制 IO 错误: {e}")
                break
            except Exception as e:
                print(f"[AudioFeature] 录制循环异常: {e}")
                break

    def _extract_and_update(self) -> None:
        """从缓冲区提取特征并更新 latest_features"""
        if len(self._buffer) < self.MIN_CHUNKS_FOR_WINDOW // 2:
            # 数据不足，跳过本轮
            return

        # 拼接所有块
        try:
            audio_data = np.concatenate(list(self._buffer))
        except ValueError:
            return

        # openSMILE 提取
        features = _process_wav_buffer(audio_data, self.RATE)

        with self._latest_lock:
            if features is not None:
                self._latest_features["pitch"] = round(features.get("pitch", 0.0), 1)
                self._latest_features["loudness"] = round(features.get("loudness", 0.0), 4)
                self._latest_features["mfcc"] = features.get("mfcc", [0.0] * 13)
                self._latest_features["voicing_prob"] = round(
                    features.get("voicing_prob", 0.0), 4
                )
                # VAD：浊音概率 > 阈值 且 响度 > 0.05 则认为在说话
                self._latest_features["speaking"] = (
                    features.get("voicing_prob", 0.0) > self._vad_threshold
                    and features.get("loudness", 0.0) > 0.05
                )


# ------------------------------------------------------------------------------
# 全局单例（延迟启动）
# ------------------------------------------------------------------------------
_audio_extractor: AudioFeatureExtractor | None = None


def start_audio_extractor() -> AudioFeatureExtractor:
    """启动全局音频特征提取器"""
    global _audio_extractor
    if _audio_extractor is None:
        _audio_extractor = AudioFeatureExtractor()
    _audio_extractor.start()
    return _audio_extractor


def get_audio_extractor() -> AudioFeatureExtractor | None:
    """获取全局音频特征提取器（未启动则返回 None）"""
    return _audio_extractor


def feed_audio_chunk_globally(base64_data: str) -> bool:
    """全局音频 chunk 注入接口，供 WebSocket handler 调用"""
    extractor = _audio_extractor
    if extractor is None:
        return False
    return extractor.feed_audio_chunk(base64_data)
