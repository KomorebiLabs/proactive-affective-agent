# 婉情AI — API 契约文档

> 本文档定义婉情AI系统中所有 HTTP / WebSocket / SSE 接口的请求与响应格式。
> 所有前后端及 Java↔Python 通信均须遵循本文档定义的数据结构。

---

## 一、整体架构

```
前端 (Vue3)
  ├─ WebSocket ws://localhost:8000/ws        ──► Python FastAPI (perception/main.py)
  │     ├─ 接收: video_frame (摄像头实时流)
  │     ├─ 接收: perception_update (AI分析结果)
  │     └─ 接收: voice_play (TTS音频播放)
  │
  ├─ HTTP POST /api/v1/session/start        ──► Java Spring Boot :8080
  │     └─ 创建用户会话，返回 sessionId
  │
  ├─ HTTP POST /api/v1/chat/stream (SSE)     ──► Java Spring Boot :8080
  │     └─ Java 透传到:
  │           POST http://localhost:8001/internal/v1/agent/invoke
  │           ──► Python Agent (Agent/main.py)
  │                 LangGraph 图执行
  │           ◄── SSE 流: chunk / is_end / vector / ui_action
  │           ◄── Java 透传到前端
  │
  └─ 前端须在所有聊天前先调用 /session/start 获取 sessionId

Python 感知服务 (perception/main.py, 端口 8000)
  ├─ POST /internal/v1/session/update    ──► Java 调用，切换 Redis session_id
  ├─ WebSocket /ws                       ──► 接收前端控制指令
  └─ WS 广播 /voice_play 指令            ──► 触发 TTS 并推送播放消息

Python Agent (Agent/main.py, 端口 8001)
  └─ POST /internal/v1/agent/invoke (SSE) ──► Java AgentClient 调用
        └─ LangGraph: collect → fuse → decide → [route] → generate → log → return
```

---

## 二、前端发起接口

### 2.1 创建用户会话

**端点:** `POST /api/v1/session/start`
**调用时机:** 每次用户进入前，前端必须先调用此接口获取有效的 `sessionId`，后续所有请求均携带此 ID。

**请求头:**
```
Content-Type: application/json
```

**请求体:**
```json
{
  "subjectName": "张三",
  "experimentGroup": "实验组A"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `subjectName` | string | 是 | 用户姓名 |
| `experimentGroup` | string | 否 | 用户分组 |

**响应（成功，HTTP 200）:**
```json
{
  "code": 200,
  "message": "success",
  "data": {
    "sessionId": "sess_a1b2c3d4e5f6...",
    "status": "ready"
  }
}
```

**副作用:** Java 后端会向 Python 感知服务发送 `POST /internal/v1/session/update`，将 Redis 中的 session_id 从 `"default"` 切换为新创建的 `sessionId`，确保各用户数据隔离。

**错误响应（会话已存在或参数错误）:**
```json
{
  "code": 400,
  "message": "参数错误或会话已存在",
  "data": null
}
```

---

### 2.2 发起聊天（SSE 流式）

**端点:** `POST /api/v1/chat/stream`
**协议:** Server-Sent Events（`text/event-stream`）
**调用时机:** 用户发送消息时。

**请求头:**
```
Content-Type: application/json
Authorization: Bearer <sessionId>   ← 注意：必须携带 Bearer 前缀
Accept: text/event-stream
```

**请求体:**
```json
{
  "message": "我今天心情不太好"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message` | string | 是 | 用户输入文本 |

**SSE 响应格式:**

每个 SSE data line 格式为：`data: <json>\n\n`

#### 非末帧（逐字流式）:
```json
data: {"chunk": "我", "is_end": false}\n\n
data: {"chunk": "在", "is_end": false}\n\n
data: {"chunk": "这", "is_end": false}\n\n
```

#### 末帧（包含完整结果）:
```json
data: {"chunk": "...完整回复末尾...", "is_end": true, "reply": "完整关怀回复文本", "vector": {"喜悦": 0.2, "悲伤": 0.8, "愤怒": 0.1, "恐惧": 0.0, "厌恶": 0.0, "惊讶": 0.3, "踏实感": 0.1, "期待": 0.2}, "ui_action": {"color": "blue", "pulse": "medium"}, "action": "subtle", "urgency": "medium", "strategy": "共情倾听", "intervention_score": 0.65, "trace_id": "a1b2c3d4e5f6", "timestamp_ms": 1749991234567, "session_id": "sess_abc123", "intervention_alert": {"show_popup": true, "urgency": "medium", "message": "婉晴感受到你可能心情有些不好，需要聊聊吗？"}}\n\n
```

**末帧完整字段说明（Plan1-A 统一版）:**

| 字段 | JSON key | 类型 | 说明 |
|------|----------|------|------|
| 文本分片 | `chunk` | string | 当前字符/token；末帧为完整回复末尾 |
| 结束标记 | `is_end` | boolean | `true` 表示本条为末帧 |
| 完整回复 | `reply` | string | 完整 AI 关怀回复（仅末帧有） |
| OCC 向量 | `vector` | object | OCC 八维情感向量，键为中文标签，值为 0-1 浮点数 |
| UI 指令 | `ui_action` | object | `{color, pulse}`，控制前端光晕效果 |
| 干预决策 | `action` | string | `silent` / `subtle` / `intervene` |
| 紧迫度 | `urgency` | string | `low` / `medium` / `high` |
| 策略名 | `strategy` | string/null | 心理学技术名称（如"5-4-3-2-1着陆技术"） |
| 干预评分 | `intervention_score` | float | 0.0~1.0，Agent 计算的干预紧迫度评分 |
| 追踪 ID | `trace_id` | string | 本次调用唯一追踪 ID（Plan1-A） |
| 时间戳 | `timestamp_ms` | int | 毫秒级 Unix 时间戳（Plan1-A） |
| 会话 ID | `session_id` | string | 当前会话 ID（Plan1-A） |

**`ui_action` 枚举值:**

| color | 对应情感类型 | pulse | 脉冲速度参数 |
|-------|------------|-------|-------------|
| `blue` | 焦虑/悲伤 | `slow` | 0.2 |
| `orange` | 沮丧/低落 | `medium` | 0.5 |
| `green` | 喜悦/安心 | `fast` | 0.8 |
| `purple` | 愤怒/激动 | `very_fast` | 0.95 |
| `neutral` | 中性/平静 | `slow` | 0.2 |

**`action` 干预决策语义（Plan1-C 三端统一）:**

| action | 语义 | 前端表现 |
|--------|------|---------|
| `silent` | 无显式回复干预（可有状态更新） | 不弹关怀弹窗，静默模式 |
| `subtle` | 轻干预/提示型响应 | 可弹低优先级提示 |
| `intervene` | 显式深度干预回复 | 弹中等/高优先级干预弹窗 |

> **注意：** `silent` 时 urgency 强制为 `low`，`intervene` 时 urgency 通常为 `medium` 或 `high`。

**错误帧格式（Plan1-E/P1-2）：**
当 SSE 流发生错误时（如 Agent 不可用），返回结构化错误帧：
```json
{"is_end": true, "is_error": true, "error_code": "AGENT_SSE_ERROR", "error_message": "婉晴暂时无法回复，请稍后重试。", "recoverable": true, "reply": "婉晴暂时无法回复，请稍后重试。", "action": "subtle", "urgency": "low", "trace_id": "error-sse-1749991234567", "timestamp_ms": 1749991234567, "session_id": "sess_abc123"}
```

**错误帧字段说明：**

| 字段 | JSON key | 类型 | 说明 |
|------|----------|------|------|
| 错误标记 | `is_error` | boolean | `true` 表示本帧为错误帧 |
| 错误码 | `error_code` | string | 错误类型，如 `AGENT_SSE_ERROR` / `AGENT_PRE_CALL_ERROR` |
| 错误信息 | `error_message` | string | 人类可读的错误描述 |
| 可恢复 | `recoverable` | boolean | `true`=可重试，`false`=需人工介入 |

> 前端应优先检查 `is_error`，若为 `true` 则按 `recoverable` 判断走重试或降级提示。

---

### 2.3 WebSocket 实时通道

**端点:** `ws://localhost:8000/ws`

**连接建立:**
```javascript
const socket = new WebSocket('ws://localhost:8000/ws')
socket.onopen = () => { console.log('已连接婉晴感知总线') }
```

**服务端推送消息格式（由 Python 推送，前端接收）:**

#### 视频帧（摄像头实时画面）
```json
{
  "type": "video_frame",
  "data": "data:image/jpeg;base64,<base64_encoded_image>"
}
```
> 前端将此字符串赋值给 `<img :src="appStore.videoFrameData">` 即可显示。

#### 感知更新（AI 分析结果）
```json
{
  "type": "perception_update",
  "data": {
    "timestamp": "2026-03-21T14:30:00",
    "behavior": "正在专注工作",
    "emotion": "平静",
    "complex_emotion": "安心",
    "vector": {"喜悦": 0.3, "悲伤": 0.1, ...},
    "analysis": "用户面部表情平静，视线稳定",
    "image": "data:image/jpeg;base64,..."
  }
}
```

#### TTS 音频播放
```json
{
  "type": "voice_play",
  "data": "http://localhost:8000/audio/xxx.mp3"
}
```
> ⚠️ **安全注意：** 建议前端仅接受以 `http://localhost:8000/audio/` 开头的 URL，拒绝外部链接。

**自动重连:** `socket.onclose` 中使用 `setTimeout(connectPerceptionBus, 3000)` 自动重连。

---

## 三、Java → Python Agent 接口（内部）

### 3.1 调用 Agent 推理（SSE）

**端点:** `POST /internal/v1/agent/invoke`
**调用方:** Java `AgentClient.callAgentStream()`
**协议:** Server-Sent Events

**请求体（JSON）:**
```json
{
  "session_id": "sess_a1b2c3d4e5f6...",
  "user_message": "我今天心情不太好",
  "emotion_history": [
    {"timestamp": 1742524800000, "primary_emotion": "悲伤", "intensity": 0.6},
    {"timestamp": 1742524700000, "primary_emotion": "焦虑", "intensity": 0.4}
  ],
  "user_id": "张三",
  "task_phase": "companion_task"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 是 | 当前用户会话 ID |
| `user_message` | string | 是 | 用户最新输入文本 |
| `emotion_history` | array | 否 | 最近情感历史（最多 `history_limit` 条） |
| `user_id` | string | 否 | 用户标识 |
| `task_phase` | string | 否 | 任务阶段，默认 `"companion_task"` |
| `history_limit` | integer | 否 | 忽略（Python 端不支持此字段） |

**SSE 响应格式:** 与 2.2 节完全一致，前端直接透传。

---

### 3.2 通知感知服务切换 session_id

**端点:** `POST /internal/v1/session/update`
**调用方:** Java `SessionServiceImpl.notifyPerceptionServiceSessionUpdate()`
**触发时机:** `POST /api/v1/session/start` 成功后立即调用

**请求体:**
```json
{
  "session_id": "sess_a1b2c3d4e5f6...",
  "user_id": "张三"
}
```

**响应（成功）:**
```json
{
  "code": 0,
  "message": "session updated",
  "session_id": "sess_a1b2c3d4e5f6..."
}
```

> ⚠️ **实现状态：** 此接口目前在 `perception/main.py` 中存在，但 `Agent/main.py`（独立 Agent 进程）中**未实现**，需要将 `perception/main.py` 中的该路由合并到 `Agent/main.py` 或确保 Java 始终调用 `perception/main.py` 的实例。

---

## 四、Python 感知服务内部接口

### 4.1 Redis 数据写入（感知微服务 → Redis）

**Key 格式:** `emotion:realtime:{session_id}`
**写入频率:** 10Hz（每 100ms 一帧）
**写入方式:** `SET`（覆盖式，无 TTL）

**数据结构:**
```json
{
  "timestamp": 1742524800000,
  "session_id": "sess_xxx",
  "au": {
    "AU1": 0.0, "AU2": 0.0, "AU4": 0.85, "AU5": 0.0,
    "AU6": 0.0, "AU12": 0.2, "AU15": 0.6, "AU17": 0.0,
    "primary_emotion": "sad",
    "confidence": 0.78
  },
  "head_pose": {
    "pitch": -12.3,
    "yaw": 5.1,
    "roll": -1.2
  },
  "blink_rate": 8.4,
  "audio": {
    "pitch": 185.3,
    "loudness": 0.42,
    "mfcc": [0.0, 0.1, 0.2, ...],
    "speaking": false
  },
  "focus_level": 0.72
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `timestamp` | int (ms) | 帧时间戳 |
| `session_id` | string | 当前会话 ID |
| `au.*` | float [0-1] | 面部动作单元强度（AU4=皱眉, AU12=微笑等） |
| `au.primary_emotion` | string | AU 模型推断的情绪（英文: neutral/happy/sad/angry/fear/disgust/surprise） |
| `head_pose.pitch` | float | 俯仰角（负值=低头，-40°以下可能表示看手机/走神，-40°以上均视为专注） |
| `blink_rate` | float | 眨眼频率（次/分钟），>25 表示紧张 |
| `audio.pitch` | float | 基频 F0（Hz） |
| `audio.speaking` | bool | 是否正在说话（VAD） |
| `focus_level` | float [0-1] | 专注度，1=完全专注 |

> ⚠️ **注意:** `voicing_prob` 在 Python 音频提取器中计算，但未写入 Redis。

---

### 4.2 Redis 数据读取（Python Agent → Redis）

**Key:** `emotion:realtime:{session_id}`（与写入方相同）
**读取方式:** `GET`（无缓冲池，每次独立请求）
**读取触发:** 由 LangGraph 节点 `collect_perception` 在每次推理循环时调用
**读取频率:** 非实时——由 LangGraph 调用频率决定（通常为用户每轮交互一次），**不是 10Hz**

**降级策略:**
- 若 Redis 中无该 key（返回 `None`）→ 使用默认中性感知数据 → 专注模式降级为走神模式

---

## 五、OCC 八维情感向量格式

### 5.1 字段对照表

| OCC 标签（中文） | OCC 标签（英文） | 含义 | 高值提示 |
|----------------|----------------|------|---------|
| 喜悦 | joy | 用户愉悦、正向反馈 | 微笑、眼神明亮 |
| 悲伤 | sadness | 失落、无助 | 眉头紧锁、声音低沉 |
| 愤怒 | anger | 挫败、被冒犯 | 脸红、语速加快 |
| 恐惧 | fear | 担忧、不安全感 | 眨眼增加、回避眼神 |
| 厌恶 | disgust | 排斥、反感 | 皱眉、鼻子皱起 |
| 惊讶 | surprise | 意外、震惊 | 眉毛抬高、嘴巴张开 |
| 踏实感 | well_grounding | 平静、安全、被支持 | 眼神稳定、放松 |
| 期待 | anticipation | 对未来的预期 | 眼神明亮、主动行为 |

### 5.2 前端 EmotionRadar 标签顺序（固定，不可改变）

```javascript
const OCC_LABELS = ["喜悦", "悲伤", "愤怒", "恐惧", "厌恶", "惊讶", "踏实感", "期待"]
```

向量中各值范围必须为 **0.0 ~ 1.0**（已由 `appStore.js` 归一化）。

---

## 六、前端情绪类型映射

后端返回的 OCC 向量最大值为 `primary_emotion`（中文标签），前端通过 `emotionMap` 映射到立绘文件名：

```javascript
const emotionMap = {
  '喜悦': '开心', '悲伤': '悲伤', '愤怒': '愤怒',
  '恐惧': '恐惧', '厌恶': '厌恶', '惊讶': '惊讶',
  '踏实感': '平静', '期待': '平静',
  '好奇': '好奇', '害羞': '害羞', '焦虑': '焦虑', '无奈': '无奈'
}
```

> ⚠️ **关键要求:** 后端 Agent 输出的 `primary_emotion` 必须从 OCC 中文标签列表中选取，不可输出其他标签。

---

## 七、端口分配约定

| 服务 | 默认端口 | 说明 |
|------|----------|------|
| Vue 前端（Vite dev） | 5173 | `npm run dev` |
| Java Spring Boot | 8080 | `mvn spring-boot:run` |
| Python 感知服务（main.py） | 8000 | `python perception/main.py` |
| Python Agent（Agent/main.py） | 8001 | `python Agent/main.py` |

> Java 中 `application.yml` 配置:
> - `agent.engine.url` → Python Agent 地址（默认 `http://localhost:8001`）
> - `perception.service.url` → Python 感知服务地址（默认 `http://localhost:8000`）

---

## 八、已知缺口（TODO）

| ID | 描述 | 优先级 |
|----|------|--------|
| T-01 | `/internal/v1/session/update` 端点需在 `Agent/main.py` 中实现 | P0 |
| T-02 | 前端未调用 `POST /api/v1/session/start`，直接生成假的 sessionId | P0 |
| T-03 | mock_agent 与真实 Agent 使用不同端口（8000 vs 8001），需统一 | P0 |
| T-04 | `voice_play` 的 `data` URL 无校验，存在安全风险 | P1 |
| T-05 | SSE 解析的 `catch (_) {}` 空 catch 块无日志 | P1 |
| T-06 | `agentAbortController` 组件卸载时未 abort | P1 |
| T-07 | WS 重连定时器在组件卸载后仍会执行 | P2 |
| T-08 | `colorMap` 中 `orange` → `negative_sad` 映射可能有误 | P2 |
| T-09 | `videoFrameData` 以 base64 字符串存储，每帧触发 Vue 响应式更新 | P2 |
| T-10 | `ChatWindow` deep watcher 每 SSE chunk 触发滚动 | P2 |
| T-11 | `updateLastAIMessage` 为 O(n)，应为 O(1) | P3 |
| T-12 | Redis Python 客户端未列入 `perception/requirements.txt` | P1 |
