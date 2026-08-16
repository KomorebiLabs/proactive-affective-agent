# P01 - Python感知引擎

## 模块名称

`backend/ai_assistant/core/perception_engine.py`

---

## 职责描述

`PerceptionEngine` 是Python感知微服务的**核心引擎模块**，负责：

1. **摄像头采集**：从摄像头持续读取视频帧
2. **MediaPipe面部检测**：使用MediaPipe Holistic提取面部关键点
3. **眨眼频率检测**：基于眼睑开合度计算眨眼频率
4. **头部姿态估算**：估算头部俯仰角、偏航角、翻滚角
5. **AU情绪识别**：调用HuggingFace模型识别面部动作单元
6. **Redis写入**：将感知数据以10Hz频率写入Redis

---

## 核心架构

### 线程模型

```
┌─────────────────────────────────────────────────────┐
│                    主线程                            │
│                 (PerceptionEngine)                   │
│  ┌─────────────────────────────────────────────┐   │
│  │           10Hz 采样循环                       │   │
│  │  1. 从帧队列取最新帧                          │   │
│  │  2. MediaPipe面部检测                         │   │
│  │  3. 提取感知数据                              │   │
│  │  4. 写入Redis                                │   │
│  │  5. 触发慢车道回调                           │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
          ↑ 线程安全队列
┌─────────────────────────────────────────────────────┐
│               摄像头采集线程                           │
│  ┌─────────────────────────────────────────────┐   │
│  │  cv2.VideoCapture.read()                     │   │
│  │  → push_frame(frame)                         │   │
│  └─────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 感知数据格式

```python
{
    "timestamp": 1709123456789,  # Unix毫秒
    "session_id": "xxx",
    "au": {
        "AU1": 0.1, "AU2": 0.0, "AU4": 0.5,  # 动作单元强度
        "AU12": 0.3, "AU15": 0.1,
        "primary_emotion": "neutral",  # 初判情绪
        "confidence": 0.7              # 置信度
    },
    "head_pose": {
        "pitch": -5.2,   # 俯仰角（度）
        "yaw": 2.1,      # 偏航角
        "roll": 0.5      # 翻滚角
    },
    "blink_rate": 15.0,  # 眨眼频率（次/分钟）
    "audio": {
        "pitch": 200.0,  # 音调（Hz）
        "loudness": 0.5, # 响度
        "mfcc": [...],   # MFCC系数
        "speaking": False # 是否在说话
    },
    "focus_level": 0.8   # 专注度（0~1）
}
```

---

## 核心代码结构

### 类结构

```python
class PerceptionEngine:
    def __init__(self, session_id="default", ...):
        # MediaPipe初始化
        self._face_mesh = mp_face.FaceMesh(...)
        
        # 子模块
        self._blink_detector = BlinkDetector()
        self._head_pose_estimator = HeadPoseEstimator()
        self._au_model = get_au_model()
        
        # 线程控制
        self._frame_queue = Queue(maxsize=5)
        self._running = False
        
    def start(self):
        """启动摄像头采集线程和主处理线程"""
        self._camera_thread = threading.Thread(target=self._camera_loop)
        self._thread = threading.Thread(target=self._run_loop)
        self._camera_thread.start()
        self._thread.start()
```

### 核心方法

| 方法名 | 作用 |
|--------|------|
| `start()` | 启动感知引擎 |
| `stop()` | 安全停止感知引擎 |
| `push_frame(frame)` | 接收摄像头帧（线程安全） |
| `get_latest_frame()` | 获取最新帧 |
| `set_session_id(session_id)` | 更新会话ID |
| `register_perception_callback(cb)` | 注册感知回调 |

---

## 关键实现细节

### 1. 摄像头采集

```python
def _camera_loop(self):
    cap = cv2.VideoCapture(0)  # 默认摄像头
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    
    while self._camera_running:
        ret, frame = cap.read()
        if ret:
            self.push_frame(frame)  # 线程安全写入队列
        time.sleep(0.05)  # 控制采集频率(~20fps)
```

### 2. MediaPipe面部检测

```python
def _extract_perception(self, frame, results, current_time):
    h, w = frame.shape[:2]
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = self._face_mesh.process(rgb_frame)
    
    if results.multi_face_landmarks:
        landmarks = results.multi_face_landmarks[0]
        
        # 头部姿态
        head_pose = self._head_pose_estimator.update_from_landmarks(...)
        
        # 眨眼频率
        eye_openness = self._compute_eye_openness(landmarks, w, h)
        self._blink_detector.update(current_time, eye_openness)
        blink_rate = self._blink_detector.get_blink_rate()
        
        # AU模型（降频3Hz）
        if current_time - self._last_au_time >= self._au_model_interval:
            au_result = self._au_model.predict(frame)
            self._last_au_time = current_time
```

### 3. 眨眼检测器

```python
class BlinkDetector:
    def update(self, timestamp, eye_openness):
        """记录眼睑开合度"""
        self._history.append((timestamp, eye_openness))
    
    def get_blink_rate(self):
        """计算60秒窗口内的眨眼频率"""
        now = self._history[-1][0]
        cutoff = now - self._window_seconds
        window_data = [(t, v) for t, v in self._history if t >= cutoff]
        
        blink_count = self._count_peaks(window_data)
        elapsed = window_data[-1][0] - window_data[0][0]
        rate = blink_count * (60.0 / elapsed)
        return max(0.0, min(60.0, rate))
```

### 4. Redis写入

```python
def _write_to_redis(self, perception_data):
    redis_client = self._ensure_redis()
    key = f"emotion:realtime:{self.session_id}"
    redis_client.set(key, json.dumps(perception_data))
```

---

## 数据流示例

```mermaid
flowchart LR
    A[cv2摄像头] -->|BGR帧| B[帧队列]
    B -->|取帧| C[PerceptionEngine]
    C -->|RGB转换| D[MediaPipe FaceMesh]
    D -->|面部关键点| E[HeadPoseEstimator<br/>BlinkDetector]
    D -->|图像| F[AU Model]
    E -->|头部姿态<br/>眨眼频率| G[感知数据融合]
    F -->|AU强度| G
    G -->|完整数据| H[Redis写入]
    H -->|Key: emotion:realtime:{session_id}| I[Redis]
    
    style G fill:#f9f,stroke:#333,stroke-width:2px
```

---

## 配置与环境依赖

| 配置项 | 说明 |
|--------|------|
| MediaPipe | 面部关键点检测 |
| OpenCV | 摄像头采集 |
| Redis | 感知数据缓存 |
| HuggingFace | AU情绪模型 |
| numpy | 数值计算 |

---

## 常见问题与调试

### Q1: 摄像头无法打开
**症状**：`VideoCapture`返回False。

**解决方案**：模块自动切换到模拟摄像头模式

### Q2: MediaPipe检测失败
**症状**：面部关键点为空。

**排查步骤**：
1. 检查光照条件
2. 确认摄像头角度
3. 检查`min_detection_confidence`参数

### Q3: 眨眼频率异常
**症状**：眨眼频率过高或过低。

**原因**：阈值设置不当或噪声干扰

**调整**：`BLINK_PEAK_THRESHOLD`参数

### Q4: Redis写入失败
**症状**：感知数据未写入Redis。

**排查步骤**：
1. 检查Redis服务是否启动
2. 确认网络连接
3. 查看日志中的错误信息

---

## 相关文件

| 文件 | 关系 |
|------|------|
| `perception_models.py` | HuggingFace AU模型封装 |
| `audio_feature_extractor.py` | 音频特征提取 |
| `config.py` | 感知配置 |
| `Agent/src/emotion/perception.py` | Agent端感知数据读取 |
