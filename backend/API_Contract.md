# Wanqing-AI 系统核心 API 接口契约文档 (API Contract V2.0)

## 一、 系统架构角色与边界声明 (Architecture Constraints)

1. **Java Spring Boot (端口 8080)**：系统躯干与唯一 HTTP 网关。负责所有 HTTP 请求鉴权、路由分发、MySQL/Redis 持久化。
2. **Python Agent 引擎 (端口 8001)**：核心大脑。负责执行 LangGraph 决策、RAG 检索、生成回复和 UI 指令。
3. **Python 感知引擎 (端口 8000)**：感官系统。负责 10Hz 多模态采集（摄像头+麦克风），直接写入 Redis。
4. **前端 (Vue3)**：通过 HTTP 与 Java (8080) 通信进行对话和反馈；通过 WebSocket 直连 Python 感知服务 (8000) 接收实时感知数据（视频帧/OCC 向量），以保证低延迟。

---

## 二、 全局统一响应格式 (Global Response Format)

为了保证前后端对接的规范性，**所有非流式 (Non-Streaming) 的 HTTP 响应**，必须严格封装在以下 `Result<T>` 格式中：

```json
{
  "code": 200,
  "message": "success",
  "data": {}
}
```

---

## 三、 对外暴露接口 (Java Spring Boot 提供给前端 Vue3)

### 3.1 用户会话初始化

- **接口路径**: `POST /api/v1/session/start`
- **描述**: 记录用户信息，生成唯一会话 ID。
- **请求体 (Request)**:

```json
{
  "subjectName": "张三",
  "experimentGroup": "A_Group"
}
```

- **响应体 (Response)**:

```json
{
  "code": 200,
  "message": "会话创建成功",
  "data": {
    "sessionId": "sess_123456789",
    "status": "ready"
  }
}
```

### 3.2 聊天消息与流式响应 (SSE)

- **接口路径**: `POST /api/v1/chat/stream`
- **描述**: 前端发送文本，Java 接收后转发给 Python Agent，并将 Agent 的回复以 SSE (Server-Sent Events) 形式流式推回前端。
- **请求头**: `Authorization: Bearer <session_id>`
- **请求体 (Request)**:

```json
{
  "message": "我今天真的很难受，代码一直报错。"
}
```

- **响应格式 (SSE Stream)**:

```
data: {"chunk": "看", "is_end": false}
data: {"chunk": "起", "is_end": false}
data: {"chunk": "来", "is_end": false}
data: {"chunk": "", "is_end": true, "ui_action": {"color": "blue", "pulse": "slow"}, "action": "subtle", "urgency": "low", "reply": "看起来起", "vector": {"喜悦": 0.2, ...}, "strategy": null, "intervention_score": 0.3, "trace_id": "a1b2c3d4", "timestamp_ms": 1749991234567, "session_id": "sess_xxx"}
```

> **末帧统一字段说明（Plan1-A）：**
> 所有 `is_end=true` 的最终帧必须包含以下字段：
> `action` (silent/subtle/intervene), `urgency` (low/medium/high), `intervention_score` (0.0~1.0),
> `trace_id` (追踪ID), `timestamp_ms` (毫秒时间戳), `session_id` (会话ID)

> **`action` 干预决策语义（Plan1-C 三端统一）：**
> - `silent`：无显式回复干预（可有状态更新），urgency 强制为 low
> - `subtle`：轻干预/提示型响应，urgency 通常为 low 或 medium
> - `intervene`：显式深度干预回复，urgency 通常为 medium 或 high

> **错误帧格式（Plan1-E）：**
> 当 SSE 流发生错误时，返回结构化错误帧：
> ```json
> data: {"is_end": true, "is_error": true, "error_code": "AGENT_SSE_ERROR", "error_message": "婉晴暂时无法回复，请稍后重试。", "recoverable": true, "reply": "婉晴暂时无法回复，请稍后重试。", "action": "subtle", "urgency": "low", "trace_id": "error-sse-1749991234567", "timestamp_ms": 1749991234567}
> ```
> 字段说明：`is_error` (bool) | `error_code` (string) | `error_message` (string) | `recoverable` (bool)

### 3.3 感知数据实时推送通道 (WebSocket)

- **接口路径**: `ws://localhost:8000/ws`
- **描述**: 前端直连 Python 感知服务（8000），接收实时感知数据推送。消息类型包括：
  - `video_frame`：摄像头画面 base64 帧（10Hz）
  - `perception_update`：OCC 情感向量更新
  - `voice_play`：TTS 语音播放指令（仅限 `http://localhost:8000` 开头的音频 URL）

### 3.4 心理学 RAG 知识库上传

- **接口路径**: `POST /api/v1/knowledge/upload`
- **描述**: 心理学专家上传整理好的 Markdown 或 PDF 文件。Java 接收文件后，通过内部网络转发给 Python Agent 引擎进行向量化处理。
- **请求类型**: `multipart/form-data` (包含 file 字段和 category 标签)
- **响应体 (Response)**:

```json
{
  "code": 200,
  "message": "文件上传并向量化成功",
  "data": {
    "fileName": "CBT_Manual.md",
    "chunksInserted": 128
  }
}
```

---

## 四、 内部服务通信契约 (Java <--> Python)

### 4.1 Java 请求 Python Agent 大脑进行决策 (HTTP)

- **接口路径**: `POST http://localhost:8001/internal/v1/agent/invoke`
- **说明**: Java 在收到前端聊天请求后，拼接历史记录、情感历史和 user_rejection_penalty，向 Agent 请求决策。Agent 返回 SSE 流，Java 解析后透传给前端。
- **请求体 (Java -> Python)**:

```json
{
  "session_id": "sess_123456789",
  "user_message": "我今天真的很难受",
  "history_limit": 10
}
```

- **响应说明**: Python 服务应返回 SSE 格式的数据流给 Java，Java 再原样/解析后透传给前端。

### 4.2 Java 转发知识库文件给 Python (HTTP)

- **接口路径**: `POST http://localhost:8001/internal/v1/rag/upload`
- **描述**: Java 收到前端上传的 Markdown/TXT 文件后，以 `multipart/form-data` 转发给 Python Agent。Agent 将文件追加保存到 `knowledge_cards/` 目录，然后触发 ChromaDB 向量库增量重建。返回 `{"file_name": "...", "chunks_inserted": N}`。

---

## 五、 感知数据交换契约 (Python 感知引擎 -> Redis)

### 5.1 多模态特征高频写入

- **描述**: Python 感知引擎（MediaPipe + HuggingFace AU + openSMILE）以固定帧率（10Hz）分析画面和声音，直接将结果覆盖写入 Redis。
- **Redis Key 格式**: `emotion:realtime:{session_id}`
- **Redis 数据类型**: String (存储 JSON)
- **写入方**: `perception/ai_assistant/core/perception_engine.py` → `PerceptionEngine._write_to_redis()`
- **消费方**: `Agent/src/emotion/perception.py` → `get_latest_perception()` → `fuse_emotion_node()`

### 5.2 Redis Value 完整 JSON Schema

```json
{
  "timestamp": 1709123456789,
  "session_id": "sess_123456",
  "au": {
    "AU1": 0.12,
    "AU2": 0.08,
    "AU4": 0.85,
    "AU5": 0.15,
    "AU6": 0.12,
    "AU7": 0.05,
    "AU9": 0.03,
    "AU12": 0.08,
    "AU15": 0.72,
    "AU17": 0.20,
    "AU25": 0.10,
    "AU26": 0.05,
    "primary_emotion": "sad",
    "confidence": 0.78
  },
  "head_pose": {
    "pitch": -12.5,
    "yaw": 3.2,
    "roll": 1.1
  },
  "blink_rate": 28.5,
  "audio": {
    "pitch": 210.5,
    "loudness": 0.65,
    "mfcc": [-2.34, 1.21, 0.88, -0.45, 0.12, 0.33, -0.21, 0.55, 0.18, -0.09, 0.22, -0.33, 0.11],
    "speaking": false
  },
  "focus_level": 0.42
}
```

### 5.3 各字段说明

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `timestamp` | long | 感知引擎 | Unix 毫秒时间戳 |
| `session_id` | string | 会话上下文 | 当前用户会话 ID |
| `au.*` | dict | HuggingFace FER2013 + 情绪→AU反推 | 面部动作单元强度（0~1），primary_emotion 为英文标签 |
| `au.primary_emotion` | string | FER2013 模型 | 英文标签：angry/disgust/fear/happy/neutral/sad/surprise |
| `au.confidence` | float | FER2013 模型 | 模型置信度（0~1） |
| `head_pose.pitch` | float | MediaPipe face mesh | 俯仰角（度），负值=低头，正值=抬头 |
| `head_pose.yaw` | float | MediaPipe face mesh | 偏航角（度），负值=左偏，正值=右偏 |
| `head_pose.roll` | float | MediaPipe face mesh | 翻滚角（度），负值=左倾，正值=右倾 |
| `blink_rate` | float | MediaPipe 眨眼检测器 | 眨眼频率（次/分钟），>25 表示焦虑信号 |
| `audio.pitch` | float | openSMILE eGeMAPS | 基频 F0（Hz），>250 表示高唤醒 |
| `audio.loudness` | float | openSMILE eGeMAPS | 响度（0~1归一化） |
| `audio.mfcc` | list[float] | openSMILE eGeMAPS | 13维 MFCC 系数 |
| `audio.speaking` | bool | openSMILE VAD | 是否正在说话 |
| `focus_level` | float | 感知引擎融合计算 | 专注度（0~1），由头部稳定性+眨眼评分融合 |

### 5.4 使用方

Python Agent 在执行 LangGraph 节点决策时，通过读取该 Redis Key 获取用户即时的真实情绪数据。

```
Agent/src/emotion/perception.py
    └── get_latest_perception(session_id)
            └── redis.get(f"emotion:realtime:{session_id}")
                    └── json.loads() → PerceptionData
                            └── fuse_emotion_node(state)
                                    └── state.current_emotion → decide_intervention_node
```

### 5.5 会话 ID 更新机制

当 Java 业务层创建新的用户会话时，需通过内部接口通知 Python 感知服务更新会话 ID：

```python
# Java 调用 Python 感知服务
POST http://localhost:8000/internal/v1/session/update
Body: {"session_id": "sess_new_session_id", "user_id": "张三"}
```

（Python 感知服务内部调用）
```python
from services.monitor_service import monitor_service
monitor_service.update_session_id("sess_new_session_id")
```
