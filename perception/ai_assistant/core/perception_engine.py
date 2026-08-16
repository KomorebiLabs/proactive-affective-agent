# ==============================================================================
# Wanqing Backend - 感知微服务核心引擎
# ==============================================================================
# 职责：
#   1. 从 MonitorService 接收摄像头帧（Thread-Safe Queue）
#   2. MediaPipe Holistic 提取面部关键点 + 头部姿态 + 眨眼频率
#   3. 调用 HuggingFace AU/情绪模型获取 AU 近似强度
#   4. 融合音频特征（来自 AudioFeatureExtractor）
#   5. 按 10Hz 频率将结构化感知数据写入 Redis
#
# 线程模型：
#   - 主线程：PerceptionEngine.run()，10Hz 采样 + 推理循环
#   - MediaPipe 回调线程：由 MediaPipe 内部管理（同步调用）
#   - Redis 写入：主线程内直接操作（轻量）
#
# Redis 数据格式：
#   Key: emotion:realtime:{session_id}
#   Value: JSON（与 Agent/src/models/schemas.py 中的 PerceptionData 对齐）
# ==============================================================================

from __future__ import annotations

import cv2
import json
import math
import threading
import time
from collections import deque
from queue import Queue, Empty
from typing import Any

import numpy as np

# MediaPipe
import mediapipe as mp
from mediapipe.framework.formats import landmark_pb2

# 本地模块
from .perception_models import get_au_model
from .audio_feature_extractor import get_audio_extractor
from ai_assistant.utils import config

# 从配置中读取权重
FOCUS_HEAD_WEIGHT = config.FOCUS_HEAD_STABILITY_WEIGHT
FOCUS_BLINK_WEIGHT = config.FOCUS_BLINK_RATE_WEIGHT
FOCUS_GAZE_WEIGHT = config.FOCUS_GAZE_DEVIATION_WEIGHT
FOCUS_NORMAL_BLINK = config.FOCUS_BLINK_NORMAL_RATE


# ==============================================================================
# 常量定义
# ==============================================================================

# MediaPipe 模型路径（可选，本地为 None 则使用内置）
MP_MODEL_PATH = None

# 眨眼检测参数
NORMAL_BLINK_RATE = FOCUS_NORMAL_BLINK  # 从配置读取正常眨眼频率
BLINK_WINDOW_SECONDS = 60.0   # 统计窗口（秒）
BLINK_PEAK_THRESHOLD = 0.6    # 眼睑开合度峰值阈值（归一化）
MIN_BLINK_WIDTH_SECONDS = 0.1  # 最短眨眼持续时间（过滤噪声）

# 采样参数（约 0.67Hz，即每 1.5 秒一次分析）
SAMPLE_INTERVAL = 1.5  # 秒

# Redis
REDIS_HOST = "localhost"
REDIS_PORT = 6379
REDIS_DB = 0


# ==============================================================================
# 眨眼频率检测器
# ==============================================================================

class BlinkDetector:
    """
    基于眼睑开合度峰值检测的眨眼频率计算器。

    算法：
      1. 持续追踪左眼和右眼的眼睑开合度（两眼外角的垂直距离归一化）
      2. 使用滑动窗口检测峰值（开合度 < 阈值 → 闭眼 → 峰值）
      3. 过滤过短峰值（眨眼宽度 < 0.1秒）
      4. 60秒滑动窗口内统计峰值数量 → 眨眼频率（次/分钟）
    """

    def __init__(self, window_seconds: float = BLINK_WINDOW_SECONDS):
        # 眼睑开合度历史（时间戳 + 归一化值）
        self._history: deque[tuple[float, float]] = deque(maxlen=5000)
        self._window_seconds = window_seconds

    def update(self, timestamp: float, eye_openness: float) -> None:
        """输入一帧的眼睑开合度（归一化 0~1，0=完全闭合）"""
        self._history.append((timestamp, eye_openness))

    def get_blink_rate(self) -> float:
        """
        计算当前 60 秒窗口内的眨眼频率（次/分钟）。
        如果窗口内数据不足 10 秒，返回默认值 15.0。
        """
        if not self._history:
            return NORMAL_BLINK_RATE

        now = self._history[-1][0]
        cutoff = now - self._window_seconds

        # 过滤时间窗口内的数据
        window_data = [(t, v) for t, v in self._history if t >= cutoff]

        if len(window_data) < 100:  # 约10秒数据（按30fps算）
            return NORMAL_BLINK_RATE

        # 峰值检测
        blink_count = self._count_peaks(window_data)

        # 转换为次/分钟
        elapsed = window_data[-1][0] - window_data[0][0]
        if elapsed < 1.0:
            return NORMAL_BLINK_RATE

        rate = blink_count * (60.0 / elapsed)

        # 物理限制（0~60次/分钟）
        return max(0.0, min(60.0, rate))

    @staticmethod
    def _count_peaks(window_data: list[tuple[float, float]]) -> int:
        """统计眨眼次数（眼睑闭合的峰值）"""
        if len(window_data) < 3:
            return 0

        values = [v for _, v in window_data]
        n = len(values)
        blink_count = 0
        in_blink = False
        blink_start_idx = 0

        for i in range(1, n - 1):
            # 简单峰值检测：当前点比前后都低
            if values[i] < values[i - 1] and values[i] < values[i + 1]:
                # 过滤：峰值需要低于阈值
                if values[i] < BLINK_PEAK_THRESHOLD:
                    if not in_blink:
                        in_blink = True
                        blink_start_idx = i
                elif in_blink:
                    # 峰值结束，检查宽度
                    blink_duration = window_data[i][0] - window_data[blink_start_idx][0]
                    if blink_duration >= MIN_BLINK_WIDTH_SECONDS:
                        blink_count += 1
                    in_blink = False

        return blink_count


# ==============================================================================
# 头部姿态估算器
# ==============================================================================

class HeadPoseEstimator:
    """
    基于 MediaPipe face mesh 估算头部三维姿态角。

    方法：使用 6 个头面部基准点（鼻尖、两个眼角、两个嘴角、下巴尖）
    估算头部相对于摄像头的偏转角度。

    注意：这是近似估算（无深度传感器情况下），精度有限但足以满足
    走神/专注模式判断需求。
    """

    # 6 个关键点的 MediaPipe face mesh 索引
    KEYPOINT_INDICES = {
        "nose_tip": 1,
        "left_eye_corner": 33,
        "right_eye_corner": 263,
        "left_mouth_corner": 61,
        "right_mouth_corner": 291,
        "chin": 152,
    }

    def __init__(self):
        self._last_pose = {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}

    def update_from_landmarks(
        self,
        landmarks: landmark_pb2.NormalizedLandmarkList,
        image_width: int,
        image_height: int,
    ) -> dict[str, float]:
        """
        从 MediaPipe face mesh 地标更新头部姿态估算。

        使用三角剖分法：
          - 以两眼中心为基准线
          - 鼻尖相对于基准线的偏移 → yaw（左右偏转）
          - 下巴尖相对于基准线的偏移 → pitch（上下点头）
          - 两眼连线与水平线的夹角 → roll（左右倾斜）
        """
        try:
            pts = {}
            for name, idx in self.KEYPOINT_INDICES.items():
                lm = landmarks.landmark[idx]
                pts[name] = (lm.x * image_width, lm.y * image_height)

            # 两眼中心
            eye_center_x = (pts["left_eye_corner"][0] + pts["right_eye_corner"][0]) / 2
            eye_center_y = (pts["left_eye_corner"][1] + pts["right_eye_corner"][1]) / 2

            # 眼距（用于归一化）
            eye_dist = math.sqrt(
                (pts["right_eye_corner"][0] - pts["left_eye_corner"][0]) ** 2
                + (pts["right_eye_corner"][1] - pts["left_eye_corner"][1]) ** 2
            )
            if eye_dist < 1e-6:
                return self._last_pose

            # Roll：两眼连线与水平线夹角
            dx = pts["right_eye_corner"][0] - pts["left_eye_corner"][0]
            dy = pts["right_eye_corner"][1] - pts["left_eye_corner"][1]
            roll = math.degrees(math.atan2(dy, dx))

            # Pitch：鼻尖相对于两眼连线的垂直偏移
            nose_offset = pts["nose_tip"][1] - eye_center_y
            pitch = math.degrees(math.atan2(nose_offset, eye_dist))

            # Yaw：鼻尖相对于两眼连线的水平偏移
            nose_lateral = pts["nose_tip"][0] - eye_center_x
            yaw = math.degrees(math.atan2(nose_lateral, eye_dist))

            self._last_pose = {
                "pitch": round(pitch, 1),
                "yaw": round(yaw, 1),
                "roll": round(roll, 1),
            }

        except (KeyError, IndexError):
            pass

        return self._last_pose

    def get_pose(self) -> dict[str, float]:
        """获取最近一次估算的姿态角"""
        return self._last_pose


# ==============================================================================
# 感知微服务核心引擎
# ==============================================================================

class PerceptionEngine:
    """
    多模态感知微服务核心引擎。

    工作流程：
      1. 接收来自 MonitorService 的摄像头帧（Thread-Safe Queue）
      2. 主循环以 10Hz 采样：
         a. 从队列取最新帧（丢弃中间帧）
         b. MediaPipe 面部检测 + 地标提取
         c. 调用 AU/情绪模型（降频，3Hz）
         d. 融合最新音频特征
         e. 计算眨眼频率和头部姿态
         f. 写入 Redis
      3. 提供 start()/stop() 生命周期管理

    线程安全：
      - 帧队列：Queue（线程安全）
      - 最新音频特征：AudioFeatureExtractor 内部已有锁
      - Redis 写入：主线程内操作，无并发问题
    """

    def __init__(
        self,
        session_id: str = "default",
        redis_host: str = REDIS_HOST,
        redis_port: int = REDIS_PORT,
        redis_db: int = REDIS_DB,
    ):
        self.session_id = session_id

        # MediaPipe 初始化（精简模式：仅面部）
        mp_face = mp.solutions.face_mesh
        mp_drawing = mp.solutions.drawing_utils
        mp_styles = mp.solutions.drawing_styles

        self._face_mesh = mp_face.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,   # 精细地标（包含眼部、嘴唇关键点）
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        # 子模块
        self._blink_detector = BlinkDetector()
        self._head_pose_estimator = HeadPoseEstimator()
        self._au_model = get_au_model()

        # 帧队列（来自 MonitorService 的 broadcast_frame）
        self._frame_queue: Queue = Queue(maxsize=5)

        # 控制标志
        self._running = False
        self._thread: threading.Thread | None = None
        self._camera_thread: threading.Thread | None = None

        # 摄像头控制
        self._camera_running = False
        self._camera_capture = None  # cv2.VideoCapture

        # 帧缓存（线程安全）
        self._frame_lock = threading.Lock()
        self._last_frame: np.ndarray | None = None  # 缓存最新帧

        # Redis 连接（延迟初始化）
        self._redis = None
        self._redis_host = redis_host
        self._redis_port = redis_port
        self._redis_db = redis_db

        # 降频控制：AU 模型以 3Hz 调用（节省算力）
        self._au_model_interval = 1 / 3.0  # ~0.333秒
        self._last_au_time = 0.0

        # 统计
        self._frame_count = 0
        self._last_sample_time = 0.0

        # 慢车道回调（PerceptionEngine → MonitorService → decision_service → chat_service）
        self._on_perception_callback: callable | None = None

        print(f"[PerceptionEngine] 感知引擎初始化完成 (session={session_id})")

    # --------------------------------------------------------------------------
    # 外部调用接口
    # --------------------------------------------------------------------------

    def set_session_id(self, session_id: str) -> None:
        """更新当前会话 ID"""
        self.session_id = session_id
        print(f"[PerceptionEngine] 会话 ID 更新为: {session_id}")

    def register_perception_callback(self, cb: callable) -> None:
        """
        注册慢车道回调（由 MonitorService 调用）。
        每轮感知分析完成后，perception_data 以同步方式传入回调。
        回调函数应尽快返回，内部自行通过 asyncio 异步执行重操作。
        """
        self._on_perception_callback = cb
        print("[PerceptionEngine] 慢车道回调已注册")

    def push_frame(self, frame: np.ndarray) -> None:
        """
        接收一帧图像（由 MonitorService 调用，线程安全）。
        使用 put_nowait 避免阻塞摄像头主循环。
        """
        try:
            self._frame_queue.put_nowait(frame.copy())
        except Exception:
            # 队列满时丢弃旧帧（取最新）
            try:
                while not self._frame_queue.empty():
                    self._frame_queue.get_nowait()
                self._frame_queue.put_nowait(frame.copy())
            except Exception:
                pass

    def get_latest_frame(self) -> np.ndarray | None:
        """
        获取缓存的最新帧（供 MonitorService 广播到前端使用）。
        注意：使用线程锁保护，确保读取时数据不会被写入。
        """
        with self._frame_lock:
            return self._last_frame.copy() if self._last_frame is not None else None

    def start(self) -> None:
        """启动感知引擎主循环（独立线程）"""
        if self._running:
            return
        self._running = True
        
        # 启动摄像头采集线程
        self._camera_thread = threading.Thread(target=self._camera_loop, daemon=True)
        self._camera_thread.start()
        print("[PerceptionEngine] 摄像头采集线程已启动")
        
        # 启动主感知处理线程
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print("[PerceptionEngine] 感知引擎主循环已启动")

    def stop(self) -> None:
        """安全停止感知引擎"""
        self._running = False
        self._camera_running = False
        
        if self._camera_thread and self._camera_thread.is_alive():
            self._camera_thread.join(timeout=3.0)
        
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        
        if self._camera_capture:
            try:
                self._camera_capture.release()
            except Exception:
                pass
        
        self._close_redis()
        print("[PerceptionEngine] 感知引擎已停止")

    # --------------------------------------------------------------------------
    # 摄像头采集线程
    # --------------------------------------------------------------------------

    def _camera_loop(self) -> None:
        """独立线程：从摄像头持续读取帧并推入队列"""
        self._camera_running = True
        
        # 打开摄像头（0 = 默认摄像头）
        cap = cv2.VideoCapture(0)
        
        if not cap.isOpened():
            print("[PerceptionEngine] 警告：无法打开摄像头，将生成模拟帧")
            self._camera_capture = None
            # 使用模拟帧模式运行
            self._simulated_camera_loop()
            return
        
        self._camera_capture = cap
        
        # 设置摄像头分辨率（降低以节省资源）
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_FPS, 30)
        
        print(f"[PerceptionEngine] 摄像头已打开 (FPS={cap.get(cv2.CAP_PROP_FPS)})")
        
        while self._camera_running and self._running:
            try:
                ret, frame = cap.read()
                if not ret:
                    print("[PerceptionEngine] 摄像头读取失败，尝试重新连接...")
                    time.sleep(1)
                    cap.release()
                    time.sleep(0.5)
                    cap = cv2.VideoCapture(0)
                    if cap.isOpened():
                        self._camera_capture = cap
                        print("[PerceptionEngine] 摄像头重新连接成功")
                    else:
                        # 多次重连失败，切换到模拟模式
                        print("[PerceptionEngine] 多次重连失败，切换到模拟摄像头模式")
                        cap.release()
                        self._simulated_camera_loop()
                        return
                    continue
                
                # 将帧推入队列（丢弃队列中的旧帧，只保留最新）
                self.push_frame(frame)
                
                # 控制采集频率（不超过 20fps）
                time.sleep(0.05)
                
            except Exception as e:
                print(f"[PerceptionEngine] 摄像头采集异常: {e}")
                time.sleep(0.1)
        
        cap.release()
        print("[PerceptionEngine] 摄像头已关闭")

    def _simulated_camera_loop(self) -> None:
        """模拟摄像头模式（无真实摄像头时使用）"""
        self._camera_running = True
        
        print("[PerceptionEngine] 使用模拟摄像头模式")
        
        while self._camera_running and self._running:
            try:
                # 生成一个 480x640 的随机彩色噪声帧作为模拟
                fake_frame = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
                # 添加一些结构让它看起来更像人脸区域
                # 在中央画一个椭圆代表"人脸"
                center = (320, 240)
                axes = (120, 150)
                cv2.ellipse(fake_frame, center, axes, 0, 0, 360, (200, 180, 160), -1)
                
                self.push_frame(fake_frame)
                time.sleep(0.1)  # 10fps
                
            except Exception as e:
                print(f"[PerceptionEngine] 模拟摄像头异常: {e}")
                time.sleep(0.1)
        
        print("[PerceptionEngine] 模拟摄像头已停止")

    # --------------------------------------------------------------------------
    # 主循环
    # --------------------------------------------------------------------------

    def _run_loop(self) -> None:
        """10Hz 主采样循环"""
        last_sample = time.time()

        while self._running:
            try:
                # 等待采样间隔
                elapsed = time.time() - last_sample
                sleep_time = SAMPLE_INTERVAL - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
                last_sample = time.time()

                # 从队列取最新帧（丢弃中间帧）
                frame = self._get_latest_frame()
                if frame is None:
                    continue

                self._frame_count += 1

                # MediaPipe 面部检测
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = self._face_mesh.process(rgb_frame)

                # 提取感知数据
                perception_data = self._extract_perception(
                    frame=frame,
                    results=results,
                    current_time=time.time(),
                )

                # 写入 Redis
                if perception_data:
                    self._write_to_redis(perception_data)

                # 慢车道：触发回调（monitor_service 注册）
                if self._on_perception_callback and perception_data:
                    try:
                        self._on_perception_callback(perception_data)
                    except Exception as cb_e:
                        print(f"[PerceptionEngine] 慢车道回调异常: {cb_e}")

            except Exception as e:
                print(f"[PerceptionEngine] 主循环异常: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(0.5)

    def _get_latest_frame(self) -> np.ndarray | None:
        """从队列中取最新帧（忽略中间帧）并缓存"""
        frame = None
        try:
            while True:
                frame = self._frame_queue.get_nowait()
        except Empty:
            pass
        # 缓存最新帧（线程安全）
        with self._frame_lock:
            if frame is not None:
                self._last_frame = frame
        return frame

    def _extract_perception(
        self,
        frame: np.ndarray,
        results,
        current_time: float,
    ) -> dict[str, Any] | None:
        """从一帧提取完整感知数据"""
        h, w = frame.shape[:2]

        # 默认数据（无面部时使用）
        au_data = {
            "AU1": 0.0, "AU2": 0.0, "AU4": 0.0, "AU5": 0.0,
            "AU6": 0.0, "AU7": 0.0, "AU9": 0.0,
            "AU12": 0.0, "AU15": 0.0, "AU17": 0.0,
            "AU25": 0.0, "AU26": 0.0,
            "primary_emotion": "neutral",
            "confidence": 0.0,
        }
        head_pose = {"pitch": 0.0, "yaw": 0.0, "roll": 0.0}
        blink_rate = NORMAL_BLINK_RATE
        eye_openness_avg = 0.8

        # 有面部检测结果
        if results.multi_face_landmarks:
            landmarks = results.multi_face_landmarks[0]

            # --- 头部姿态 ---
            head_pose = self._head_pose_estimator.update_from_landmarks(landmarks, w, h)

            # --- 眨眼检测 ---
            eye_openness_avg = self._compute_eye_openness(landmarks, w, h)
            self._blink_detector.update(current_time, eye_openness_avg)
            blink_rate = self._blink_detector.get_blink_rate()

            # --- AU 模型（降频 3Hz）---
            if current_time - self._last_au_time >= self._au_model_interval:
                au_result = self._au_model.predict(frame)
                if au_result:
                    au_data.update(au_result.get("au_intensities", {}))
                    au_data["primary_emotion"] = au_result.get("primary_emotion", "neutral")
                    au_data["confidence"] = au_result.get("confidence", 0.0)
                self._last_au_time = current_time

        # --- 音频特征 ---
        audio_features = self._get_audio_features()

        # --- focus_level ---
        focus_level = self._compute_focus_level(head_pose, blink_rate)

        return {
            "timestamp": int(current_time * 1000),
            "session_id": self.session_id,
            "au": au_data,
            "head_pose": head_pose,
            "blink_rate": round(blink_rate, 1),
            "audio": audio_features,
            "focus_level": round(focus_level, 3),
        }

    def _compute_eye_openness(
        self,
        landmarks: landmark_pb2.NormalizedLandmarkList,
        image_width: int,
        image_height: int,
    ) -> float:
        """
        计算平均眼睑开合度（归一化 0~1）。
        使用左眼和右眼的上下眼睑点估算。
        """
        try:
            # MediaPipe face mesh 眼部和嘴唇关键点（refine_landmarks=True 时可用）
            # 左眼：33(外角), 160(上), 158(下)
            # 右眼：263(外角), 385(上), 387(下)
            left_eye_indices = {"outer": 33, "top": 160, "bottom": 158}
            right_eye_indices = {"outer": 263, "top": 385, "bottom": 387}

            def eye_openness(indices: dict) -> float:
                top = landmarks.landmark[indices["top"]]
                bottom = landmarks.landmark[indices["bottom"]]
                outer = landmarks.landmark[indices["outer"]]

                # 上下眼睑垂直距离
                vertical = abs(top.y - bottom.y) * image_height
                # 内外眼角水平距离（用于归一化）
                horizontal = abs(
                    landmarks.landmark[263 if indices["outer"] == 33 else 33].x
                    - outer.x
                ) * image_width

                if horizontal < 1e-6:
                    return 0.5

                # 归一化（眨眼时垂直距离趋近 0）
                openness = min(1.0, vertical / (horizontal * 0.3))
                return openness

            left_openness = eye_openness(left_eye_indices)
            right_openness = eye_openness(right_eye_indices)
            return (left_openness + right_openness) / 2.0

        except (KeyError, IndexError):
            return 0.8  # 默认睁开眼睛状态

    def _get_audio_features(self) -> dict[str, Any]:
        """从 AudioFeatureExtractor 获取最新音频特征"""
        extractor = get_audio_extractor()
        if extractor is None:
            return {
                "pitch": 0.0,
                "loudness": 0.0,
                "mfcc": [0.0] * 13,
                "speaking": False,
            }

        features = extractor.get_latest()
        return {
            "pitch": features.get("pitch", 0.0),
            "loudness": features.get("loudness", 0.0),
            "mfcc": features.get("mfcc", [0.0] * 13),
            "speaking": features.get("speaking", False),
        }

    def _compute_focus_level(
        self,
        head_pose: dict[str, float],
        blink_rate: float,
    ) -> float:
        """
        计算专注度（0~1）。

        公式：
          focus = w_head*(1-head_deviation) + w_blink*blink_score + w_gaze*gaze_factor
          gaze_factor 默认为 0.5（无视线追踪数据时）

        权重从 config.py 配置读取：
          w_head = FOCUS_HEAD_STABILITY_WEIGHT (默认 0.65)
          w_blink = FOCUS_BLINK_RATE_WEIGHT (默认 0.15)
          w_gaze = FOCUS_GAZE_DEVIATION_WEIGHT (默认 0.2)
        """
        # 头部稳定性（权重提高，更依赖头部姿态）
        head_deviation = (abs(head_pose["pitch"]) + abs(head_pose["yaw"])) / 60.0
        head_deviation = min(head_deviation, 1.0)
        # 低头阅读特殊处理：pitch >= -40° 均视为专注，不惩罚
        # 严重低头（pitch < -40°）才视为走神
        if head_pose["pitch"] < -40.0:
            head_deviation = 1.0
        head_score = 1.0 - head_deviation

        # 眨眼评分（权重降低）
        blink_deviation = abs(blink_rate - NORMAL_BLINK_RATE) / NORMAL_BLINK_RATE
        blink_score = max(0.0, 1.0 - blink_deviation)

        # 使用配置中的权重进行加权合并
        focus = FOCUS_HEAD_WEIGHT * head_score + FOCUS_BLINK_WEIGHT * blink_score + FOCUS_GAZE_WEIGHT * 0.5
        return max(0.0, min(1.0, focus))

    # --------------------------------------------------------------------------
    # Redis 写入
    # --------------------------------------------------------------------------

    def _ensure_redis(self) -> Any:
        """延迟初始化 Redis 连接"""
        if self._redis is None:
            try:
                import redis
                self._redis = redis.Redis(
                    host=self._redis_host,
                    port=self._redis_port,
                    db=self._redis_db,
                    decode_responses=True,
                )
                # 测试连接
                self._redis.ping()
                print(f"[PerceptionEngine] Redis 连接成功 ({self._redis_host}:{self._redis_port})")
            except Exception as e:
                print(f"[PerceptionEngine] Redis 连接失败: {e}，感知数据将仅记录到日志")
                self._redis = None
        return self._redis

    def _write_to_redis(self, perception_data: dict[str, Any]) -> None:
        """将感知数据写入 Redis（覆盖写入）"""
        redis_client = self._ensure_redis()
        if redis_client is None:
            # 降级：打印到日志
            print(f"[Perception] (Redis unavailable) au={perception_data['au']['primary_emotion']}, blink={perception_data['blink_rate']}")
            return

        try:
            # 1. 写入感知数据（现有逻辑）
            key = f"emotion:realtime:{self.session_id}"
            redis_client.set(key, json.dumps(perception_data, ensure_ascii=False))

            # 2. 写入摄像头帧 Base64（供 Qwen-VL 分析使用）
            # 从缓存的 `_last_frame` 读取，编码为 JPEG 后转为 Base64
            frame = self._last_frame
            if frame is not None:
                import base64 as _b64
                # 压缩质量 70：平衡文件大小和画质，约减少 60% Base64 长度
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                frame_base64 = _b64.b64encode(buffer).decode('utf-8')
                frame_key = f"camera:frame:{self.session_id}"
                # 30 秒过期：确保 Agent 读取时不会拿到过于陈旧的帧
                redis_client.setex(frame_key, 30, frame_base64)
        except Exception as e:
            print(f"[PerceptionEngine] Redis 写入失败: {e}")

    def _close_redis(self) -> None:
        """关闭 Redis 连接"""
        if self._redis is not None:
            try:
                self._redis.close()
            except Exception:
                pass
            self._redis = None


# ------------------------------------------------------------------------------
# 全局单例
# ------------------------------------------------------------------------------
_perception_engine: PerceptionEngine | None = None


def get_perception_engine() -> PerceptionEngine | None:
    """获取全局感知引擎单例"""
    return _perception_engine


def create_perception_engine(session_id: str = "default") -> PerceptionEngine:
    """创建并启动全局感知引擎"""
    global _perception_engine
    if _perception_engine is not None:
        _perception_engine.stop()
    _perception_engine = PerceptionEngine(session_id=session_id)
    _perception_engine.start()
    return _perception_engine
