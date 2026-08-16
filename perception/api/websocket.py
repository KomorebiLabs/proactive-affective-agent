# backend/api/websocket.py
import base64
import json
import time
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from socket_manager import manager, MessagePriority

from services.chat_service import chat_service
from services.monitor_service import monitor_service


async def handle_websocket(websocket: WebSocket):
    """
    WebSocket 路由分发器。
    负责接收前端消息，根据 type 分发给不同的 Service。

    注意：主流对话走 Java SSE 路径（ChatController → Python Agent）。
    此 WebSocket 路由用于：
      - 感知数据推送（视频帧、情感分析）
      - TTS 语音播放（由 Agent 通过 WebSocket 客户端发送，我们再广播给前端）
      - ping/pong 心跳
      - 日报请求
    """
    # 【TTS重构】默认作为前端连接加入
    success = await manager.connect(websocket, connection_type="frontend")
    if not success:
        return

    # 标记此连接是否为 Agent（通过特定消息识别）
    is_agent_client = False
    # 【TTS重构】标记 TTS 专用通道
    is_tts_channel = False

    try:
        while True:
            data = await websocket.receive_text()

            try:
                msg_obj = json.loads(data)
                msg_type = msg_obj.get("type")

                # === Agent 客户端识别 ===
                # Agent 通过 WebSocket 连接发送 TTS 数据，我们直接广播给前端
                if msg_type == "agent_heartbeat":
                    is_agent_client = True
                    manager.mark_agent_connection(websocket)  # 【TTS重构】标记为 Agent 连接
                    print(f" [WS] Agent 客户端已连接")
                    continue

                # === 【TTS重构】TTS 专用通道识别 ===
                if msg_type == "tts_stream_start":
                    is_tts_channel = True
                    is_agent_client = True  # TTS 通道也是 Agent 客户端
                    manager.mark_tts_connection(websocket)
                    print(f" [WS] TTS 专用通道已建立")
                    continue

                # === 【TTS重构】TTS 音频块（直接发送到前端，绕过队列和视频帧）===
                if is_tts_channel and msg_type == "voice_stream":
                    recv_time = time.time()
                    stream_id = msg_obj.get("stream_id")
                    print(f" [WS→前端] [TTS通道] 收到 voice_stream (stream_id={stream_id}) 时间={recv_time:.3f}")
                    
                    # 【TTS重构关键】发送时间戳，用于前端计算延迟
                    manager.send_to_tts(websocket, {
                        "type": "voice_stream",
                        "stream_id": stream_id,
                        "data": msg_obj.get("data"),
                        "is_first": msg_obj.get("is_first", False),
                        "is_last": msg_obj.get("is_last", False),
                        "chunk_index": msg_obj.get("chunk_index", 0),
                        "send_timestamp": int(time.time() * 1000)  # 添加发送时间戳
                    })
                    continue

                # === 【TTS重构】流式音频结束（直接发送）===
                if is_tts_channel and msg_type == "voice_stream_end":
                    manager.send_to_tts(websocket, {
                        "type": "voice_stream_end",
                        "stream_id": msg_obj.get("stream_id"),
                        "total_chunks": msg_obj.get("total_chunks", 0),
                        "total_bytes": msg_obj.get("total_bytes", 0),
                        "send_timestamp": int(time.time() * 1000)
                    })
                    print(f" [WS] [TTS通道] 流式音频结束 (stream_id={msg_obj.get('stream_id')})")
                    continue

                # === Agent 发来的非 TTS 语音数据（兼容旧客户端）===
                if is_agent_client and not is_tts_channel and msg_type == "voice_play":
                    manager.broadcast({
                        "type": "voice_play",
                        "data": msg_obj.get("data")
                    }, MessagePriority.HIGH)
                    print(f" [WS] 转发 Agent TTS 语音数据（长度: {len(str(msg_obj.get('data', '')))}）")
                    continue

                # === 【TTS重构】非 TTS 通道的 voice_stream（走旧逻辑，但排除 Agent）===
                if is_agent_client and not is_tts_channel and msg_type == "voice_stream":
                    recv_time = time.time()
                    print(f" [WS→前端] 收到 voice_stream (stream_id={msg_obj.get('stream_id')}) 时间={recv_time:.3f}")
                    manager.broadcast_to_frontend({
                        "type": "voice_stream",
                        "stream_id": msg_obj.get("stream_id"),
                        "data": msg_obj.get("data"),
                        "is_first": msg_obj.get("is_first", False),
                        "is_last": msg_obj.get("is_last", False),
                        "chunk_index": msg_obj.get("chunk_index", 0)
                    })
                    continue

                # === 【TTS重构】非 TTS 通道的 voice_stream_end ===
                if is_agent_client and not is_tts_channel and msg_type == "voice_stream_end":
                    manager.broadcast_to_frontend({
                        "type": "voice_stream_end",
                        "stream_id": msg_obj.get("stream_id"),
                        "total_chunks": msg_obj.get("total_chunks", 0),
                        "total_bytes": msg_obj.get("total_bytes", 0)
                    })
                    continue

                # === 前端发来的消息 ===
                if msg_type == "chat":
                    # 【注意】此路径为 WebSocket 直接聊天（绕过了 Java Agent 干预逻辑）。
                    # 主流对话应使用 SSE 路径（前端 → Java → Python SSE）。
                    # 此处保留用于快速调试或未来独立 AI 模式。
                    user_text = msg_obj.get("text")
                    is_cbt = msg_obj.get("is_cbt", False)
                    await chat_service.handle_user_message(user_text, is_cbt=is_cbt)

                elif msg_type == "instruction":
                    action = msg_obj.get("action")
                    if action == "toggle_camera":
                        monitor_service.toggle_camera()

                elif msg_type == "ping":
                    # 【修复11】心跳响应：使用高优先级确保及时送达，并更新心跳时间
                    manager.receive_pong(websocket)
                    try:
                        await websocket.send_text(json.dumps({"type": "pong", "timestamp": int(time.time() * 1000)}))
                    except Exception:
                        pass

                elif msg_type == "voice_capture":
                    # 前端麦克风采集的音频 chunk → 注入 AudioFeatureExtractor
                    base64_data = msg_obj.get("data", "")
                    if base64_data:
                        from ai_assistant.core.audio_feature_extractor import feed_audio_chunk_globally
                        success = feed_audio_chunk_globally(base64_data)
                        if not success:
                            print(f" [WS] voice_capture chunk 注入失败（可能音频提取器未启动）")
                    continue

                elif msg_type == "voice_input":
                    # ─────────────────────────────────────────────────────────────
                    # 语音输入（按压说话 → ASR → 转文字 → 发回前端 → 继续对话）
                    # ─────────────────────────────────────────────────────────────
                    base64_audio = msg_obj.get("data", "")
                    if not base64_audio:
                        await websocket.send_text(json.dumps({
                            "type": "voice_input_result",
                            "success": False,
                            "error": "音频数据为空"
                        }))
                        continue

                    try:
                        from services.asr_service import asr_service, ASRService

                        # 1. Base64 → bytes
                        audio_bytes = base64.b64decode(base64_audio)
                        print(f" [WS] voice_input: 音频数据 {len(audio_bytes)} bytes")

                        # 2. 前端已发送 WAV 格式（RIFF/WAVE header），直接使用
                        #    若数据过小（<44 bytes）说明不是 WAV，则走 PCM→WAV 路径
                        if len(audio_bytes) > 44 and audio_bytes[:4] == b'RIFF' and audio_bytes[8:12] == b'WAVE':
                            wav_bytes = audio_bytes
                            print(f" [WS] voice_input: 使用前端传来的 WAV（{len(wav_bytes)} bytes）")
                        else:
                            # 旧版前端可能发送裸 PCM，转为 WAV
                            wav_bytes = ASRService.build_wav_from_pcm(audio_bytes)
                            print(f" [WS] voice_input: PCM {len(audio_bytes)} bytes → WAV {len(wav_bytes)} bytes")

                        # 3. 异步 ASR（不阻塞 WebSocket 主循环）
                        loop = asyncio.get_event_loop()
                        result = await loop.run_in_executor(None, asr_service.recognize, wav_bytes)

                        # 4. 解析结果：recognize 返回 (success, text) 元组
                        success, text = result

                        if success and text:
                            print(f" [WS] voice_input ASR 成功: {text}")
                            await websocket.send_text(json.dumps({
                                "type": "voice_input_result",
                                "success": True,
                                "text": text
                            }))
                        elif success and not text:
                            # 成功但返回空 → 未检测到语音
                            print(f" [WS] voice_input ASR 未检测到语音")
                            await websocket.send_text(json.dumps({
                                "type": "voice_input_result",
                                "success": False,
                                "error": "没有检测到语音内容，请靠近麦克风说话",
                                "error_type": "no_speech"
                            }))
                        else:
                            # 失败
                            print(f" [WS] voice_input ASR 失败: {text}")
                            await websocket.send_text(json.dumps({
                                "type": "voice_input_result",
                                "success": False,
                                "error": "语音识别服务暂时不可用，请稍后重试",
                                "error_type": "service_error"
                            }))
                    except Exception as e:
                        print(f" [WS] voice_input 处理异常: {e}")
                        try:
                            await websocket.send_text(json.dumps({
                                "type": "voice_input_result",
                                "success": False,
                                "error": "语音识别服务暂时不可用，请稍后重试",
                                "error_type": "exception"
                            }))
                        except Exception:
                            pass
                    continue

                elif msg_type == "request_summary":
                    await chat_service.generate_daily_summary()

            except json.JSONDecodeError:
                print(" [WS] 收到非 JSON 格式数据")

    except WebSocketDisconnect:
        manager.disconnect(websocket)
        if is_agent_client:
            print(f" [WS] Agent 客户端已断开")
    except Exception as e:
        print(f" [WS 路由异常] {e}")
        manager.disconnect(websocket)
