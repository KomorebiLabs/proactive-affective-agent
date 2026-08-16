# backend/services/monitor_service.py
import asyncio
import base64
import cv2
import threading
import time
from io import BytesIO
from PIL import Image
from datetime import datetime

import numpy as np

# 导入感知微服务引擎（新架构核心）
from ai_assistant.core.perception_engine import create_perception_engine, get_perception_engine
from ai_assistant.core.audio_feature_extractor import start_audio_extractor
from ai_assistant.utils import config as perception_config

from socket_manager import manager, MessagePriority
from services.memory_service import memory_service
from services.decision_service import decision_service


class MonitorService:
    """
    【感知服务调度中心】
    职责：
      1. 启动音频特征提取器（openSMILE）
      2. 启动感知微服务引擎（PerceptionEngine：摄像头 → MediaPipe → AU/情绪模型 → Redis）
      3. 管理感知数据的分发（视频流广播 + 结构化数据转发）

    注意：本文件不直接处理摄像头，而是由感知引擎内部的摄像头线程负责。
    """
    def __init__(self):
        self.status_text = "初始化中..."
        self.main_loop = None
        self._perception_engine = None
        self._video_broadcast_thread = None
        self._video_broadcast_running = False

    def start(self, loop):
        """由主线程启动服务"""
        self.main_loop = loop

        # 启动音频特征提取器（独立线程，麦克风资源独占）
        print("[MonitorService] 启动音频特征提取器...")
        start_audio_extractor()

        # 创建并启动感知微服务引擎
        print("[MonitorService] 启动感知微服务引擎...")
        self._perception_engine = create_perception_engine(session_id="default")

        # 注册慢车道回调：感知引擎每轮分析完成后 → 触发主动关怀链路
        self._perception_engine.register_perception_callback(self.handle_perception_data)
        print("[MonitorService] 慢车道回调已注册到感知引擎")

        # 启动视频帧广播线程（从感知引擎的帧队列读取并广播到前端）
        self._video_broadcast_running = True
        self._video_broadcast_thread = threading.Thread(target=self._video_broadcast_loop, daemon=True)
        self._video_broadcast_thread.start()
        print("[MonitorService] 视频帧广播线程已启动")

    def update_session_id(self, session_id: str) -> None:
        """
        更新感知引擎的会话 ID。
        当 Java 业务层通过 API 创建新的实验会话时，调用此方法。
        """
        if self._perception_engine is not None:
            self._perception_engine.set_session_id(session_id)
            print(f"[MonitorService] 感知引擎会话已切换: {session_id}")

    # --- 感知数据分发接口 ---

    def broadcast_frame(self, image: Image.Image):
        """
        [快车道] 实时视频流
        由感知引擎摄像头线程调用（约 20fps）
        将帧压缩后通过 WebSocket 广播到前端。
        """
        if not self.main_loop:
            return

        try:
            # 1. 压缩图像以提升 B/S 传输速度
            buffered = BytesIO()
            img_resized = image.resize((640, 360))
            img_resized.save(buffered, format="JPEG", quality=50)

            # 2. 转为 Base64 字符串
            img_str = base64.b64encode(buffered.getvalue()).decode()

            payload = {
                "type": "video_frame",
                "data": f"data:image/jpeg;base64,{img_str}"
            }

            # 【修复3】视频帧使用低优先级队列，避免挤压语音带宽
            self.main_loop.call_soon_threadsafe(manager.broadcast, payload, MessagePriority.LOW)

        except Exception:
            pass  # 视频流允许少量掉帧，不报错

    def handle_perception_data(self, perception_data: dict) -> None:
        """
        [Q1 修复] 感知引擎每轮分析完成后的回调入口。
        将原始 perception_data 适配为 handle_analysis_result 的参数格式，
        然后异步触发完整的慢车道链路（日志 → 决策 → 主动关怀）。
        """
        from datetime import datetime

        timestamp_raw_ms = perception_data.get("timestamp", 0)  # 原始整数毫秒
        timestamp = datetime.fromtimestamp(timestamp_raw_ms / 1000.0)

        # 从 AU 数据提取情绪
        au_data = perception_data.get("au", {})
        primary_emotion = au_data.get("primary_emotion", "neutral")
        confidence = au_data.get("confidence", 0.0)

        # 【修复】置信度阈值检查：当置信度低于阈值时，强制设为 neutral
        # 避免低置信度的负面情绪（angry/disgust/fear/sad）被误判
        CONFIDENCE_THRESHOLD = 0.30  # 置信度 < 30% 时直接设为 neutral

        if confidence < CONFIDENCE_THRESHOLD or primary_emotion == "neutral":
            primary_emotion = "neutral"
            confidence = 0.0

        # 从 focus_level 推断行为描述
        # 【阈值调整】专注 >= 0.4，轻度走神 >= 0.25，明显走神 < 0.25（从配置读取）
        focus_level = perception_data.get("focus_level", 0.5)
        if focus_level >= perception_config.FOCUS_THRESHOLD_CONCENTRATED:
            behavior_desc = "专注" if primary_emotion in ("happy", "neutral") else "沉思"
        elif focus_level >= perception_config.FOCUS_THRESHOLD_MILD_DAZED:
            behavior_desc = "轻度走神"
        else:
            behavior_desc = "明显走神"

        behavior_num = 1 if focus_level >= perception_config.FOCUS_THRESHOLD_CONCENTRATED else 2

        # 构造分析文本
        head_pose = perception_data.get("head_pose", {})
        audio = perception_data.get("audio", {})
        analysis_text = (
            f"情绪: {primary_emotion} (置信度 {confidence:.0%})，"
            f"专注度 {focus_level:.0%}，"
            f"眨眼 {perception_data.get('blink_rate', 0):.0f}次/分，"
            f"头部偏移 pitch={head_pose.get('pitch', 0):.1f}° yaw={head_pose.get('yaw', 0):.1f}°"
        )

        # AU 近似情绪向量（供决策使用）
        emotion_vector = self._au_to_emotion_vector(au_data)

        self.handle_analysis_result(
            timestamp=timestamp,
            analysis_text=analysis_text,
            behavior_num=behavior_num,
            behavior_desc=behavior_desc,
            emotion=primary_emotion,
            screenshot=None,
            timestamp_raw_ms=timestamp_raw_ms,
            complex_emotion=None,
            emotion_vector=emotion_vector,
        )

    def _au_to_emotion_vector(self, au_data: dict) -> dict:
        """
        将 AU 数据映射为 OCC 八维情绪向量（近似值，供决策服务使用）。

        【修复】添加最小有效阈值（MIN_VALID_THRESHOLD = 0.25）：
        当 FER2013 推断的 AU 强度低于阈值时，视为噪声/中性状态。

        设计原则：
        1. 避免 AU 冲突：同一 AU 不同时用于多个互相矛盾的情绪
        2. 使用 AU 组合：利用多个 AU 协同判断，提高准确性
        3. 系数基于心理学研究：参考 FACS AU 和 Ekman 的 AU-情绪映射

        OCC 八维情绪映射逻辑：
        - 喜悦 (occ_joy): AU12（嘴角上扬）> 0.4
        - 悲伤 (occ_sadness): AU15（嘴角下垂）+ AU1+AU4 组合
        - 愤怒 (occ_anger): AU4（皱眉）+ AU23/AU24（唇部收紧）+ AU5（瞪眼）
        - 恐惧 (occ_fear): AU1+AU4+AU5+AU7 组合（瞪眼+皱眉+眉毛上提）
        - 厌恶 (occ_disgust): AU9（皱鼻）+ AU15
        - 惊讶 (occ_surprise): AU5（瞪眼）+ AU1+AU2 + AU26（下巴下垂）
        - 踏实感 (occ_well_grounding): 1 - max(AU4, AU1) 表示放松程度
        - 期待 (occ_anticipation): AU5 + AU12 的组合（警觉+积极）
        """
        # 提取 AU 值（归一化到 0~1）
        au1 = au_data.get("AU1", 0.0)
        au2 = au_data.get("AU2", 0.0)
        au4 = au_data.get("AU4", 0.0)
        au5 = au_data.get("AU5", 0.0)
        au6 = au_data.get("AU6", 0.0)
        au7 = au_data.get("AU7", 0.0)
        au9 = au_data.get("AU9", 0.0)
        au12 = au_data.get("AU12", 0.0)
        au15 = au_data.get("AU15", 0.0)
        au17 = au_data.get("AU17", 0.0)
        au23 = au_data.get("AU23", 0.0)
        au24 = au_data.get("AU24", 0.0)
        au26 = au_data.get("AU26", 0.0)

        # 【修复】最小有效阈值：AU 值必须超过此阈值才认为是有效的情绪信号
        # FER2013 推断的 AU 可能存在噪声，设置阈值避免假阳性
        MIN_VALID_THRESHOLD = 0.25  # AU 强度必须 > 0.25 才算有效

        def _apply_threshold(value: float, threshold: float = MIN_VALID_THRESHOLD) -> float:
            """应用最小阈值，低于阈值视为 0"""
            return value if value > threshold else 0.0

        # 1. 喜悦：AU12（嘴角上扬）> 0.4 是核心指标
        joy = _apply_threshold(au12 * 0.8)

        # 2. 悲伤：AU15（嘴角下垂）> 0.4 是核心，AU1+AU4 组合是辅助
        # AU1（内眉上扬）+ AU4（皱眉）组合表示悲伤/沮丧
        sadness_eyebrow = _apply_threshold(min(au1, au4) * 0.5)
        sadness_mouth = _apply_threshold(au15 * 0.7)  # 嘴角下垂是更直接的悲伤指标
        sadness = max(sadness_eyebrow, sadness_mouth)

        # 3. 愤怒：AU4（皱眉）+ AU23/AU24（唇部收紧）组合
        # 【修复】唇部收紧（AU23/AU24）必须 > 阈值，且需要和 AU4 协同
        anger_brow = _apply_threshold(au4 * 0.5)
        anger_lip = _apply_threshold(max(au23, au24) * 0.8)
        anger_eye = _apply_threshold(au5 * 0.3)
        # 必须至少有一个强信号（唇部或眉毛），且眼睛瞪大作为辅助
        anger = max(anger_brow, anger_lip) + anger_eye * 0.2
        anger = _apply_threshold(anger)  # 最终结果也要检查阈值

        # 4. 恐惧：AU1+AU7（眉毛上扬）+ AU5（瞪眼）+ AU4（皱眉）组合
        # 恐惧需要多个 AU 同时激活
        fear_eyebrow = _apply_threshold(min(au1, au7) * 0.6)
        fear_eye = _apply_threshold(au5 * 0.4)
        fear_brow_4 = _apply_threshold(au4 * 0.3)
        fear = fear_eyebrow + fear_eye * 0.5 + fear_brow_4 * 0.2
        fear = _apply_threshold(fear)

        # 5. 厌恶：AU9（皱鼻）+ AU15（嘴角下垂）
        disgust_nose = _apply_threshold(au9 * 0.7)
        disgust_mouth = _apply_threshold(au15 * 0.4)
        disgust = max(disgust_nose, disgust_mouth) * 0.8
        disgust = _apply_threshold(disgust)

        # 6. 惊讶：AU5（瞪眼）+ AU1+AU2 + AU26（下巴下垂）
        # 惊讶是短暂的，通常 AU5 和 AU26 同时出现
        surprise_eye = _apply_threshold(au5 * 0.5)
        surprise_brow = _apply_threshold(min(au1, au2) * 0.5)
        surprise_jaw = _apply_threshold(au26 * 0.4)
        surprise = max(surprise_eye, surprise_brow) + surprise_jaw * 0.3
        surprise = _apply_threshold(surprise)

        # 7. 踏实感/安定感：1 - max(AU4, AU1) 表示放松程度
        # AU4 和 AU1 都是负面/紧张信号，低值表示踏实
        tension_signal = max(au4, au1) * 0.6
        grounding = 1.0 - tension_signal

        # 8. 期待/焦虑倾向：AU5（警觉）+ AU12（积极）组合
        # 高 AU5 + 低 AU12 = 焦虑/紧张期待
        # 高 AU5 + 高 AU12 = 积极期待
        anticipation_base = au5 * 0.4
        anticipation_valence = au12 * 0.3
        anticipation = min(1.0, anticipation_base + anticipation_valence)

        # 归一化到 [0, 1]
        return {
            "喜悦": round(min(1.0, joy), 3),
            "悲伤": round(min(1.0, sadness), 3),
            "愤怒": round(min(1.0, anger), 3),
            "恐惧": round(min(1.0, fear), 3),
            "厌恶": round(min(1.0, disgust), 3),
            "惊讶": round(min(1.0, surprise), 3),
            "踏实感": round(max(0.0, grounding), 3),
            "期待": round(min(1.0, anticipation), 3),
        }

    def handle_analysis_result(self, timestamp, analysis_text,
                               behavior_num, behavior_desc,
                               emotion, screenshot,
                               timestamp_raw_ms=None,
                               complex_emotion=None,
                               emotion_vector=None):
        """
        [慢车道] 感知引擎完成一轮 AI 分析后的回调。
        负责：存储日志 + 触发决策 + 推送结构化数据到前端。
        """
        print(f"🚀 [视觉分析完成] 行为:{behavior_desc} | 情绪:{emotion}")

        # 1. 存入本地日志
        observation_data = {
            "timestamp": timestamp,
            "behavior_num": behavior_num,
            "behavior_desc": behavior_desc,
            "emotion": emotion,
            "complex_emotion": complex_emotion,
            "vector": emotion_vector,
            "analysis": analysis_text
        }
        memory_service.save_log(observation_data)

        # 2. 计算唤醒度（归一化 L2 范数，确保 [0, 1] 范围）
        arousal = 0.0
        if emotion_vector:
            vals = list(emotion_vector.values()) if isinstance(emotion_vector, dict) else []
            if vals:
                arousal = float(np.linalg.norm(vals)) / (len(vals) ** 0.5)

        # 3. 异步触发决策服务
        if self.main_loop:
            asyncio.run_coroutine_threadsafe(
                decision_service.process_new_observation(
                    behavior_desc, emotion, complex_emotion, arousal
                ),
                self.main_loop
            )

        # 4. 推送结构化感知数据到前端
        img_str = ""
        if screenshot:
            buffered = BytesIO()
            screenshot.save(buffered, format="JPEG", quality=70)
            img_str = base64.b64encode(buffered.getvalue()).decode()

        payload = {
            "type": "perception_update",
            "data": {
                "timestamp": timestamp.isoformat() if hasattr(timestamp, 'isoformat') else str(timestamp),
                "timestamp_ms": timestamp_raw_ms,  # 整数毫秒，供前端时间戳比较用
                "behavior": behavior_desc,
                "emotion": emotion,
                "complex_emotion": complex_emotion,
                "vector": emotion_vector,
                "analysis": analysis_text,
                "image": f"data:image/jpeg;base64,{img_str}"
            }
        }

        if self.main_loop:
            # 感知更新使用普通优先级
            self.main_loop.call_soon_threadsafe(manager.broadcast, payload, MessagePriority.NORMAL)

    # --- 视频帧广播线程 ---
    
    def _video_broadcast_loop(self):
        """
        从感知引擎的帧队列读取帧，广播到前端。
        这个函数在独立线程中运行，频率约 10fps。
        """
        engine = get_perception_engine()
        if engine is None:
            print("[MonitorService] 感知引擎未初始化，无法启动视频广播")
            return

        while self._video_broadcast_running:
            try:
                # 从感知引擎获取缓存的最新帧
                frame = engine.get_latest_frame()
                if frame is not None:
                    # BGR -> RGB
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    pil_image = Image.fromarray(rgb_frame)
                    
                    # 调用 MonitorService 的广播方法
                    self.broadcast_frame(pil_image)
                else:
                    # 没有新帧时短暂等待
                    time.sleep(0.1)
            except Exception as e:
                print(f"[MonitorService] 视频广播异常: {e}")
                time.sleep(0.1)


# 单例导出
monitor_service = MonitorService()
