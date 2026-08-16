# backend/services/asr_service.py
# ==============================================================================
# Wanqing Backend - 语音识别服务（ASR）
# ==============================================================================
# 职责：
#   使用阿里云 DashScope Transcription API 进行录音文件语音转文字（ASR）
#   录音文件识别需要公网 URL，因此先将 WAV 上传到 OSS，再用 URL 提交任务
# ==============================================================================

import io
import time
import uuid
import wave

import dashscope
from dashscope.audio.asr import Transcription
from dashscope.api_entities.dashscope_response import HTTPStatus

from ai_assistant.utils import config
from ai_assistant.core.api_clients import oss_bucket


class ASRService:
    """
    【语音识别服务】
    职责：接收前端 WAV 音频数据 → 上传 OSS → 调用 DashScope Transcription API → 返回识别文字。
    """

    def __init__(self):
        # paraformer-v2: 录音文件识别推荐模型，支持任意采样率、多语种（含中文）
        self.model = "paraformer-v2"

    def recognize(self, wav_bytes: bytes) -> tuple:
        """
        同步识别：上传 WAV 到 OSS → 提交 Transcription 任务 → 轮询等待结果。
        供 run_in_executor 线程池调用。

        Args:
            wav_bytes: 完整的 WAV 格式字节流（含 RIFF/WAVE header）
        Returns:
            (success: bool, text: str) - 成功/失败状态和识别文字
            - 成功且有内容: (True, "识别文字")
            - 成功但无内容: (True, "")
            - 失败: (False, "错误描述")
        """
        oss_url = None
        try:
            # ── 调试：保存本地 WAV 文件用于排查 ──
            debug_wav_path = "debug_asr.wav"
            with open(debug_wav_path, "wb") as f:
                f.write(wav_bytes)
            print(f" [ASR] 调试: 已保存 WAV 到 {debug_wav_path} ({len(wav_bytes)} bytes)")

            # ── 验证 WAV header ──
            if len(wav_bytes) > 44:
                riff = wav_bytes[0:4]
                wave = wav_bytes[8:12]
                fmt = wav_bytes[12:16]
                data = wav_bytes[36:40]
                sample_rate = int.from_bytes(wav_bytes[24:28], 'little')
                bits_per_sample = int.from_bytes(wav_bytes[34:36], 'little')
                data_size = int.from_bytes(wav_bytes[40:44], 'little')
                print(f" [ASR] WAV Header: RIFF={riff}, WAVE={wave}, fmt={fmt}, data={data}")
                print(f" [ASR] WAV 参数: 采样率={sample_rate}Hz, 位深={bits_per_sample}bit, 数据大小={data_size}bytes")
            # ── 1. 上传 WAV 到 OSS，获取公网 URL ──
            oss_url = self._upload_to_oss(wav_bytes)
            print(f" [ASR] WAV 已上传 OSS: {oss_url}")

            # ── 2. 提交异步识别任务（支持中英双语识别）──
            print(f" [ASR] 提交识别任务: model={self.model}, language_hints=['zh', 'en']")
            task_response = Transcription.async_call(
                model=self.model,
                file_urls=[oss_url],
                language_hints=["zh", "en"],
            )

            if task_response.status_code != HTTPStatus.OK:
                error_msg = f"提交任务失败 {task_response.status_code}: {task_response.message}"
                print(f" [ASR] ❌ {error_msg}")
                return (False, error_msg)

            task_id = task_response.output.task_id
            print(f" [ASR] 任务已提交, task_id={task_id}")

            # ── 3. 轮询等待结果（最多 60 秒）──
            max_wait = 60
            start = time.time()
            while time.time() - start < max_wait:
                result = Transcription.fetch(task_id)

                if result.status_code != HTTPStatus.OK:
                    error_msg = f"查询任务失败 {result.status_code}: {result.message}"
                    print(f" [ASR] ❌ {error_msg}")
                    return (False, error_msg)

                status = result.output.task_status
                print(f" [ASR] 轮询任务状态: {status}")

                if status == "SUCCEEDED":
                    print(f" [ASR] ✅ 任务成功，正在解析结果...")
                    print(f" [ASR] result.output 内容: {result.output}")

                    # ── results 是列表，需要下载 transcription_url 获取实际文字 ──
                    results_list = result.output.results
                    if not results_list:
                        print(f" [ASR] ❌ 结果列表为空")
                        return (False, "识别结果为空")

                    first_result = results_list[0]
                    print(f" [ASR] first_result 类型: {type(first_result)}, 内容: {first_result}")

                    # 防止 first_result 仍是列表
                    if isinstance(first_result, list):
                        if first_result:
                            first_result = first_result[0]
                        else:
                            return (False, "识别结果列表内层仍为空")

                    if not isinstance(first_result, dict):
                        return (False, f"first_result 类型错误: {type(first_result)}")

                    subtask_status = first_result.get("subtask_status", "UNKNOWN")
                    print(f" [ASR] 子任务状态: {subtask_status}")

                    if subtask_status != "SUCCEEDED":
                        # 任务失败，打印详细错误
                        error_code = first_result.get("code", "UNKNOWN")
                        error_msg = first_result.get("message", "Unknown error")
                        print(f" [ASR] ❌ 子任务失败: {error_code} - {error_msg}")
                        return (False, f"识别子任务失败: {error_msg}")

                    # 从 transcription_url 下载识别结果
                    transcription_url = first_result.get("transcription_url")
                    if not transcription_url:
                        print(f" [ASR] ❌ 缺少 transcription_url")
                        return (False, "识别结果 URL 缺失")

                    print(f" [ASR] 下载识别结果: {transcription_url}")
                    import httpx
                    resp = httpx.get(transcription_url, timeout=30.0)
                    if resp.status_code != 200:
                        print(f" [ASR] ❌ 下载失败: HTTP {resp.status_code}")
                        return (False, f"下载识别结果失败: HTTP {resp.status_code}")

                    transcription_data = resp.json()
                    print(f" [ASR] transcription_data 类型: {type(transcription_data)}")
                    print(f" [ASR] 识别结果原始数据: {transcription_data}")

                    # 防止 transcription_data 是列表
                    if isinstance(transcription_data, list):
                        if transcription_data:
                            transcription_data = transcription_data[0]
                        else:
                            return (False, "transcription_data 是空列表")

                    # 解析识别文字
                    text = ""
                    if isinstance(transcription_data, dict):
                        transcripts = transcription_data.get("transcripts", [])
                        if transcripts and isinstance(transcripts, list):
                            first_transcript = transcripts[0]
                            if isinstance(first_transcript, dict):
                                text = first_transcript.get("text", "").strip()
                                sentences = first_transcript.get("sentences", [])
                                if sentences and isinstance(sentences, list):
                                    text = "".join(s.get("text", "") for s in sentences if isinstance(s, dict))
                    else:
                        return (False, f"transcription_data 类型错误: {type(transcription_data)}")

                    print(f" [ASR] ✅ 识别成功: {text}")
                    return (True, text.strip())

                elif status == "RUNNING":
                    print(f" [ASR] 任务进行中...")

                elif status in ("FAILED", "CANCELLED"):
                    error_msg = f"任务{status}: {result.output}"
                    print(f" [ASR] ❌ {error_msg}")
                    return (False, error_msg)

                time.sleep(2)

            print(f" [ASR] ❌ 等待超时（>{max_wait}s）")
            return (False, "识别超时，请重试")

        except Exception as e:
            import traceback
            print(f" [ASR] ❌ 识别异常: {e}")
            traceback.print_exc()
            return (False, f"识别异常: {str(e)}")
        finally:
            # 清理 OSS 上的临时文件
            if oss_url:
                try:
                    object_key = oss_url.split(f"{config.OSS_BUCKET}.{config.OSS_ENDPOINT}/")[-1]
                    oss_bucket.delete_object(object_key)
                    print(f" [ASR] 已清理 OSS 临时文件: {object_key}")
                except Exception as e2:
                    print(f" [ASR] 清理 OSS 文件失败（不影响识别）: {e2}")

    def _upload_to_oss(self, wav_bytes: bytes) -> str:
        """
        将 WAV 字节上传到 OSS，返回公网可访问的 URL。
        """
        object_key = f"asr_temp/{uuid.uuid4().hex}.wav"
        oss_bucket.put_object(object_key, wav_bytes)
        # 返回完整 URL: https://bucket.endpoint/object_key
        oss_url = f"https://{config.OSS_BUCKET}.{config.OSS_ENDPOINT}/{object_key}"
        return oss_url

    @staticmethod
    def build_wav_from_pcm(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
        """
        将 PCM 字节流封装为 WAV 格式字节流。

        Args:
            pcm_bytes:   原始 PCM 数据（16位小端有符号整数）
            sample_rate: 采样率，默认 16000 Hz
            channels:    声道数，默认 1（单声道）

        Returns:
            WAV 格式字节流
        """
        import struct
        bits = 16
        byte_rate = sample_rate * channels * (bits // 8)
        block_align = channels * (bits // 8)
        data_size = len(pcm_bytes)

        # WAV header: 44 bytes
        header = bytearray(44)
        # RIFF chunk descriptor
        header[0:4] = b'RIFF'
        header[4:8] = struct.pack('<I', 36 + data_size)      # FileSize - 8
        header[8:12] = b'WAVE'
        # fmt sub-chunk
        header[12:16] = b'fmt '
        header[16:20] = struct.pack('<I', 16)                # Subchunk1Size (16 for PCM)
        header[20:22] = struct.pack('<H', 1)                  # AudioFormat (1 = PCM)
        header[22:24] = struct.pack('<H', channels)           # NumChannels
        header[24:28] = struct.pack('<I', sample_rate)        # SampleRate
        header[28:32] = struct.pack('<I', byte_rate)          # ByteRate
        header[32:34] = struct.pack('<H', block_align)       # BlockAlign
        header[34:36] = struct.pack('<H', bits)               # BitsPerSample
        # data sub-chunk
        header[36:40] = b'data'
        header[40:44] = struct.pack('<I', data_size)          # Subchunk2Size

        return bytes(header) + pcm_bytes


# 单例导出
asr_service = ASRService()

# 类导出（供其他模块使用静态方法如 build_wav_from_pcm）
__all__ = ['ASRService', 'asr_service', 'build_wav_from_pcm']


# 保留模块级函数作为别名（向后兼容）
def build_wav_from_pcm(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """模块级别名，调用类静态方法"""
    return ASRService.build_wav_from_pcm(pcm_bytes, sample_rate, channels)
