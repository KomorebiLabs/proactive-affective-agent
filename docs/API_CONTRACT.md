# 婉情AI（Wanqing-AI）统一 API 契约文档

> 本文档由 `backend/API_Contract.md`（旧）与 `frontend/API_Contract.md`（较新）合并而成，**以代码为唯一事实源**逐条核对修订。
> 事实源范围：`backend/src/main/java/com/wanqing/ai/controller/*.java`（6 个控制器）及其 DTO、`Agent/main.py`、`Agent/src/memory/callback.py`、`Agent/src/memory/structured.py`、`Agent/src/utils/tts.py`、`Agent/src/utils/websocket_client.py`、`Agent/config.py`、`perception/main.py`、`perception/api/websocket.py`、`perception/services/monitor_service.py`、`perception/ai_assistant/core/perception_engine.py`、`frontend/src/App.vue`、`frontend/src/api/index.js`。
> 修订日期：2026-08-16。

---

## 目录

1. [系统架构与端口总表](#一系统架构与端口总表)
2. [Java 对前端接口（REST + SSE）](#二java-对前端接口rest--sse)
3. [Java ↔ Agent 内部接口](#三java--agent-内部接口)
4. [Java ↔ 感知服务接口](#四java--感知服务接口)
5. [前端 ↔ 感知服务 WebSocket 协议](#五前端--感知服务-websocket-协议)
6. [SSE 帧协议逐帧定义](#六sse-帧协议逐帧定义)
7. [Redis key 约定（跨服务集成总线）](#七redis-key-约定跨服务集成总线)
8. [已知实现状态说明](#八已知实现状态说明)
9. [契约修复记录](#九契约修复记录)

---

## 一、系统架构与端口总表

```
前端 (Vue3, Vite :5173)
  ├── HTTP REST/SSE ──────────────► Java Spring Boot :8080（唯一 HTTP 网关，MySQL/Redis 持久化）
  │                                   ├── SSE ──► Python Agent :8001（LangGraph 决策大脑）
  │                                   └── HTTP ─► Python 感知 :8000（会话切换通知）
  │                                        ▲
  │                                        └── HTTP 回调 ◄── Python Agent :8001（会话日志落库）
  └── WebSocket ws://...:8000/ws ──► Python 感知 :8000（视频帧/感知/TTS 流式音频/ASR）
                                         │ 10Hz 写入
                                         ▼
                                    Redis :6379（跨服务集成总线）
                                         ▲
                                    Python Agent 读取（collect_perception 节点）
```

| 服务 | 技术栈 | 默认端口 | 启动入口 | 地址配置 |
|------|--------|----------|----------|----------|
| Vue 前端 | Vue3 + Vite | 5173 | `npm run dev` | `VITE_API_BASE`（默认 `http://localhost:8080`）、`VITE_PERCEPTION_WS_URL`（默认 `ws://localhost:8000/ws`），见 `frontend/src/api/index.js` |
| Java 后端 | Spring Boot | 8080 | `mvn spring-boot:run` | `application.yml`：`agent.engine.url`（默认 `http://localhost:8001`）、`perception.service.url`（默认 `http://localhost:8000`） |
| Python Agent | FastAPI + LangGraph | 8001 | `python Agent/main.py` | 感知服务地址：`AGENT_BASE_URL`（默认 `http://localhost:8001`，仅感知服务转发用） |
| Python 感知 | FastAPI + MediaPipe/openSMILE | 8000 | `python perception/main.py` | Java 回调地址：`JAVA_CALLBACK_URL`（默认 `http://localhost:8080`） |
| Redis | — | 6379 | — | 三方共用，key 约定见[第七节](#七redis-key-约定跨服务集成总线) |
| MySQL | — | 3306 | — | 仅 Java 直连（架构约定：Python 不直连 MySQL，经回调落库） |

### 全局统一响应格式（Java 对前端）

所有非流式 HTTP 接口（`/api/v1/*`）统一封装为 `Result<T>`：

```json
{ "code": 200, "message": "success", "data": {} }
```

> 例外：`GET /health`、`GET /api/v1/info`（Java）、`GET /health`（Agent/感知）直接返回裸 JSON Map，不做 `Result` 包装；`POST /internal/v1/session/update` 返回 `{code: 0, ...}` 私有格式。

### 角色边界

1. **Java（8080）**：系统躯干与唯一对前端的 HTTP 网关，负责鉴权（`Authorization: Bearer <session_id>`）、MySQL/Redis 持久化、SSE 帧重组（注入 `intervention_alert`）、反馈惩罚计算。
2. **Agent（8001）**：核心大脑，LangGraph 决策（collect → fuse → decide → route → generate → log → return）、RAG 检索、TTS 合成（经感知服务 WS 通道下发）。
3. **感知（8000）**：感官系统，10Hz 多模态采集（摄像头 + 麦克风），直写 Redis，WS 广播视频帧/感知结果，承载 TTS 流式音频转发与前端 ASR。
4. **前端（Vue3）**：HTTP 走 Java（对话/反馈），WS 直连感知服务（低延迟实时数据）。

---

## 二、Java 对前端接口（REST + SSE）

### 2.1 接口总表

| 方法 | 路径 | 控制器 | 说明 | 响应格式 |
|------|------|--------|------|----------|
| POST | `/api/v1/session/start` | SessionController | 初始化用户会话 | `Result<SessionStartResp>` |
| POST | `/api/v1/chat/stream` | ChatController | SSE 流式聊天（帧协议见第六节） | `text/event-stream` |
| POST | `/api/v1/feedback` | FeedbackController | 干预弹窗用户反馈（**旧两份契约均未记载，本次补全**） | `Result<Void>` |
| POST | `/api/v1/knowledge/upload` | KnowledgeController | RAG 知识库上传（multipart） | `Result<Map>` |
| GET | `/health` | HealthController | 后端健康检查 | 裸 JSON |
| GET | `/api/v1/info` | HealthController | 版本/状态信息 | 裸 JSON |

### 2.2 POST /api/v1/session/start — 初始化用户会话

**请求体**（注意：字段为 **snake_case**，`SessionStartReq` 使用 `@JsonProperty` 显式映射；两字段均 `@NotBlank` 必填）：

```json
{
  "subject_name": "张三",
  "experiment_group": "default"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `subject_name` | string | 是 | 用户姓名（前端默认传 `anonymous`） |
| `experiment_group` | string | 是 | 用户分组（前端默认传 `default`） |

**响应（成功）**：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "session_id": "sess_a1b2c3d4e5f6...",
    "status": "ready"
  }
}
```

- `session_id` 生成规则：`"sess_" + UUID.randomUUID()` 去掉连字符（`SessionServiceImpl`）。
- **副作用**：成功后 Java 立即调用感知服务 `POST /internal/v1/session/update`，将 Redis 写入目标从 `"default"` 切换到新会话（见 4.1）。
- **失败**：`Result.fail(400, "参数错误或会话已存在")` 之类；参数校验失败由全局异常处理器返回 400。

### 2.3 POST /api/v1/chat/stream — SSE 流式聊天

**请求头**：

```
Content-Type: application/json
Authorization: Bearer <session_id>     ← Bearer 前缀可省略，Java 会 trim 解析
Accept: text/event-stream
```

**请求体**（`ChatMessageReq`，`message` 为 `@NotBlank` 必填）：

```json
{ "message": "我今天真的很难受，代码一直报错。" }
```

**HTTP 状态码**：

| 状态 | 条件 |
|------|------|
| 200（SSE 流） | 校验通过 |
| 400 | `Authorization` 头缺失或为空 |
| 404 | 会话不存在（`sessionService.getSessionById` 返回 null） |

**Java 侧处理流程**（`ChatController.chatStream`，约 83-354 行）：

1. 将用户消息 LPUSH 写入 `session:{session_id}:history`（保留 20 条，TTL 2 小时）；
2. 读取情感历史（`emotion:history:{session_id}`，最近 10 条）与反馈统计（`feedback:stats:{session_id}`），计算 `user_rejection_penalty = clamp(1.0 + rejection_rate * 0.5, 0.5, 1.5)`；
3. 调用 Agent `POST /internal/v1/agent/invoke`（SSE），非末帧原样透传；
4. **末帧重组**：以 Agent 末帧为基础，重写 `timestamp_ms`（Java 侧时间）、`session_id`（真实会话），并注入 `intervention_alert`（见 6.3）；
5. 流结束后写入本轮情感历史（`vector` 最大值项 → `primary_emotion` + `intensity`）；
6. SSE 超时 5 分钟；响应头含 `Cache-Control: no-cache, no-transform`、`X-Accel-Buffering: no`。

帧协议详见[第六节](#六sse-帧协议逐帧定义)。

### 2.4 POST /api/v1/feedback — 干预弹窗用户反馈

**请求体**（`FeedbackRequest`）：

```json
{
  "session_id": "sess_abc123",
  "choice": "rejected",
  "emotion_vector": {"喜悦": 0.2, "悲伤": 0.8, "愤怒": 0.1, "恐惧": 0.0, "厌恶": 0.0, "惊讶": 0.3, "踏实感": 0.1, "期待": 0.2},
  "current_emotion": "悲伤"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 是 | 会话 ID，空则 `Result.fail(400, "session_id 不能为空")` |
| `choice` | string | 是 | `accepted` / `rejected` / `ignored`，非法值返回 400 |
| `emotion_vector` | object | 否 | 反馈时 OCC 八维向量快照（默认 `{}`） |
| `current_emotion` | string | 否 | 反馈时情绪标签（默认 `""`） |

**响应**：`{"code": 200, "message": "success", "data": null}`

**副作用**：写 MySQL 反馈表 + 同步 Redis `feedback:stats:{session_id}`（TTL 24 小时，含 `rejection_rate`），供 ChatController 下轮计算 `user_rejection_penalty`。

### 2.5 POST /api/v1/knowledge/upload — RAG 知识库上传

**请求**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | file | 是 | 知识文件。**Agent 端仅接受 `.md` / `.txt`**（其他类型 Agent 返回 400；旧契约写"Markdown 或 PDF"与代码不符） |
| `category` | string | 是 | 分类标签 |

**响应**（Java 将 Agent 返回包装为 `Result`）：

```json
{
  "code": 200,
  "message": "success",
  "data": {
    "file_name": "CBT_Manual.md",
    "chunks_inserted": 128,
    "category": "default"
  }
}
```

**链路**：Java `KnowledgeServiceImpl` → Agent `POST /internal/v1/rag/upload`（见 3.2）→ 保存至 `Agent/knowledge_cards/` → ChromaDB 增量重建。

### 2.6 GET /health 与 GET /api/v1/info

```json
// GET /health
{ "status": "online", "service": "wanqing-ai-backend", "timestamp": "2026-08-16T00:00:00Z" }

// GET /api/v1/info
{ "service": "wanqing-ai-backend", "version": "1.0.0", "status": "running", "timestamp": "2026-08-16T00:00:00Z" }
```

> 两接口不做 `Result` 包装，供启动脚本与监控直接探测。

---

## 三、Java ↔ Agent 内部接口

### 3.1 POST /internal/v1/agent/invoke — Agent 决策（SSE）

- **提供方**：`Agent/main.py` `invoke_agent()`（端口 8001）
- **调用方**：Java `AgentClient.callAgentStream()`（`agent.engine.url` 配置，默认 `http://localhost:8001`）

**请求体**（Java `AgentInvokeReq` 与 Python `AgentInvokeRequest` 逐字段对齐）：

```json
{
  "session_id": "sess_abc123",
  "user_id": "张三",
  "user_message": "我今天心情不太好",
  "history_limit": 10,
  "task_phase": "ready",
  "emotion_history": [
    {"timestamp": 1742524800000, "primary_emotion": "悲伤", "intensity": 0.6}
  ],
  "conversation_history": [
    "{\"role\":\"user\",\"content\":\"我今天心情不太好\",\"timestamp\":1742524800000}"
  ],
  "user_rejection_penalty": 1.15
}
```

| 字段 | 类型 | Java 默认 | Python 默认 | 说明 |
|------|------|-----------|-------------|------|
| `session_id` | string | 必填 | 必填 | 会话 ID |
| `user_id` | string | `""` | `""` | 用户标识（取 `subject_name`） |
| `user_message` | string | 必填 | `""`（可空，主动关怀场景） | 用户最新输入 |
| `history_limit` | int | 10 | **未声明，被忽略** | 遗留字段，Python 端不消费 |
| `task_phase` | string | `"unknown"` | `"unknown"` | 任务阶段。注意：ChatController 实际传 `session.getStatus()`，即 `"ready"`，并非旧契约所写的 `"companion_task"` |
| `emotion_history` | list[dict] | `[]` | `[]` | 每条含 `timestamp`(ms)/`primary_emotion`(中文)/`intensity` |
| `conversation_history` | list[string] | `[]` | `[]` | JSON 字符串列表（`{role, content, timestamp}`），时间正序，含当前用户消息 |
| `user_rejection_penalty` | float | 1.0 | 1.0 | 拒绝惩罚系数 [0.5, 1.5]，Python 用于 `interrupt_cost = interrupt_cost * penalty` |

**响应**：`text/event-stream`（头：`Cache-Control: no-cache`、`X-Accel-Buffering: no`）。帧格式与前端 SSE 一致（见第六节），差异点：

- Agent 末帧**不携带** `intervention_alert`（由 Java 注入）；
- Agent 末帧的 `timestamp_ms`/`session_id`/`trace_id` 会被 Java 重写（`trace_id` 透传 Agent 生成的 `uuid4().hex[:16]`）；
- `strategy` 仅在非 None 时输出；
- 空回复（silent 或 subtle 无 reply）时发送单个 `ui_only` 末帧（`chunk:""`, `reply:""`）；
- 每字符间隔约 30ms（`asyncio.sleep(0.03)`）控制播报节奏；
- LangGraph 执行失败：HTTP 500（`HTTPException detail="Agent 执行失败: ..."`）；图级崩溃时降级为 `subtle + 默认回复`（"我在这里陪着你，有什么想说的吗？"）。

### 3.2 POST /internal/v1/rag/upload — 知识库转发（multipart）

- **提供方**：`Agent/main.py` `rag_upload()`
- **调用方**：Java `KnowledgeServiceImpl`

**请求**：`multipart/form-data`，字段 `file`（文件）+ `category`（Form，可空）。

**处理**：仅接受 `.md`/`.txt`（否则 400）→ 保存到 `Agent/knowledge_cards/` → ChromaDB 增量重建（`sync_knowledge_base()`，新增 chunk 数 = before/after 计数差）。

**响应**（裸 JSON，Java 包装后返回前端）：

```json
{ "file_name": "CBT_Manual.md", "chunks_inserted": 128, "category": "default" }
```

### 3.3 POST /internal/conversation/log — Agent 回调 Java 写会话日志

> **两份旧契约均未记载此接口，本次补全。** 这是"Python 不直连 MySQL"架构约定的落地通道。

- **提供方**：Java `ConversationController`（`/internal/conversation`，无需鉴权，仅供内网 localhost 调用；请求头 `X-Internal-Source` 可选标识）
- **调用方**：`Agent/src/memory/callback.py` `call_java_conversation_log()`（`Agent/config.py`：`JAVA_CALLBACK_URL` 默认 `http://localhost:8080`，路径 `/internal/conversation/log`，超时 10s）
- **触发时机**：LangGraph `log_session_node` 每轮对话结束后（`export_session_log()` 序列化）；回调失败仅告警不阻塞主流程

**请求体**（`Agent/src/memory/structured.py export_session_log()` 输出，与 Java `SessionLog` 实体对齐）：

```json
{
  "session_id": "sess_abc123",
  "user_message": "我今天真的很累",
  "ai_reply": "听起来你今天辛苦了……",
  "intervention_action": "subtle",
  "intervention_urgency": "low",
  "intervention_score": 0.42,
  "perception_snapshot": { "au": { "...": 0.0 } },
  "emotion_vector": { "喜悦": 0.1, "悲伤": 0.7 },
  "decision_detail": { "reasoning": "...", "strategy": "共情倾听" },
  "retrieved_knowledge": [ { "card_id": "...", "title": "..." } ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | string | 必填，空则 `Result.fail(400)`；会话不存在则 `Result.fail(404)` |
| `user_message` / `ai_reply` | string | 本轮对话双方文本 |
| `intervention_action` / `intervention_urgency` | string | 干预决策（silent/subtle/intervene；low/medium/high） |
| `intervention_score` | float | 干预评分（Java 转 BigDecimal 落库） |
| `perception_snapshot` / `emotion_vector` / `decision_detail` / `retrieved_knowledge` | object/list | JSON 序列化后落库对应列 |

**响应**：`Result<Void>`（成功 `{"code":200,"message":"success","data":null}`；写库异常 `Result.fail(500, "写入失败: ...")`）。

**副作用**：Redis `INCR session:turn_index:{session_id}` 原子生成 `turn_index`，插入 MySQL `session_logs` 表。

### 3.4 GET /health（Agent）

```json
{ "status": "online", "service": "wanqing-agent" }
```

---

## 四、Java ↔ 感知服务接口

### 4.1 POST /internal/v1/session/update — 切换感知会话

- **提供方**：`perception/main.py` `update_session()`（端口 8000）
- **调用方**：Java `SessionServiceImpl.notifyPerceptionServiceSessionUpdate()`，在 `POST /api/v1/session/start` 成功后立即调用

**请求体**：

```json
{ "session_id": "sess_abc123", "user_id": "张三" }
```

**响应**（注意是 `code: 0` 的私有格式，**不是** Java 的 `Result` 200 格式）：

```json
{ "code": 0, "message": "session updated", "session_id": "sess_abc123" }
```

**副作用**：`monitor_service.update_session_id()` 切换感知引擎的 Redis 写入目标 key（`emotion:realtime:{session_id}` / `camera:frame:{session_id}`）。

### 4.2 POST /internal/v1/agent/invoke（感知服务遗留同路径端点）

`perception/main.py` 中存在**同名遗留端点**，与 Agent 的 `/internal/v1/agent/invoke` 路径相同但行为不同：

- 行为：HTTP 转发到 `AGENT_BASE_URL`（默认 `http://localhost:8001`）→ Agent 不可用时使用**本地规则引擎降级**（基于 `emotion_history` 最新强度阈值生成回复与 OCC 向量）；
- 该端点自身 SSE 输出**缺少** `trace_id` / `timestamp_ms` / `session_id` / `intervention_score` 字段；
- Java `AgentClient` 走 `agent.engine.url`（8001），**不经过**此端点；它主要为单跑感知服务的调试拓扑保留。

### 4.3 感知服务辅助端点

| 方法 | 路径 | 说明 | 响应 |
|------|------|------|------|
| GET | `/` | 服务信息 | `{status, service: "wanqing-perception", port: 8000, agent_proxy}` |
| GET | `/health` | 健康检查 | `{status: "ok", service: "wanqing-perception"}` |
| GET | `/model_status` | 情绪模型加载状态（供 Agent 健康检查调用） | `{model_loaded: bool, model_id: "trpakov/vit-face-expression", message}` |

---

## 五、前端 ↔ 感知服务 WebSocket 协议

**端点**：`ws://localhost:8000/ws`（`frontend/src/api/index.js` 的 `PERCEPTION_WS_URL`，可用 `VITE_PERCEPTION_WS_URL` 覆盖）
**路由实现**：`perception/api/websocket.py` `handle_websocket()` + `perception/socket_manager.py`（消息带优先级：LOW=视频帧 / NORMAL=感知更新 / HIGH=语音）

### 5.1 服务端 → 前端（下行）

| 消息类型 | 优先级 | 频率 | 说明 |
|----------|--------|------|------|
| `video_frame` | LOW | 约 10fps | 摄像头实时画面 |
| `perception_update` | NORMAL | 感知分析轮次 | AI 分析结果（OCC 向量等） |
| `voice_play` | HIGH | TTS 完成时 | 非流式整段音频（遗留兼容路径） |
| `voice_stream` | TTS 专用通道直发 | 流式 | TTS 音频块（**旧两份契约均未记载**） |
| `voice_stream_end` | TTS 专用通道直发 | 每流一次 | TTS 流结束标记 |
| `pong` | 高优先级单播 | 心跳应答 | 每 25s 一次 |
| `voice_input_result` | 单播 | 按需 | 按压说话 ASR 识别结果 |

**video_frame**（640×360 JPEG quality=50）：

```json
{ "type": "video_frame", "data": "data:image/jpeg;base64,<base64>" }
```

**perception_update**（注意 `timestamp` 为 ISO 字符串、`timestamp_ms` 为整数毫秒，前端以 `timestamp_ms` 与 SSE 时间戳对齐）：

```json
{
  "type": "perception_update",
  "data": {
    "timestamp": "2026-08-16T14:30:00",
    "timestamp_ms": 1742524800000,
    "behavior": "正在专注工作",
    "emotion": "平静",
    "complex_emotion": "安心",
    "vector": {"喜悦": 0.3, "悲伤": 0.1, "愤怒": 0.0, "恐惧": 0.0, "厌恶": 0.0, "惊讶": 0.0, "踏实感": 0.6, "期待": 0.2},
    "analysis": "用户面部表情平静，视线稳定",
    "image": "data:image/jpeg;base64,..."
  }
}
```

**voice_play**（遗留整段播放，Agent 端现已内嵌 base64 数据 URL）：

```json
{ "type": "voice_play", "data": "data:audio/mp3;base64,<base64>" }
```

> **安全约定（以代码为准）**：前端 `App.vue` 仅接受以 `data:audio` 开头的内嵌数据，**拒绝一切外部 URL**（旧契约"仅限 http://localhost:8000 开头的音频 URL"的说法已过时，base64 内嵌从根本上消除了 SSRF 风险）。

**voice_stream**（Agent TTS 专用通道 → 感知服务 → 前端；`send_timestamp` 由感知服务转发时附加，前端用于计算端到端延迟）：

```json
{
  "type": "voice_stream",
  "stream_id": "tts_20260816_001",
  "data": "<base64 mp3 chunk>",
  "is_first": true,
  "is_last": false,
  "chunk_index": 0,
  "send_timestamp": 1742524800123
}
```

**voice_stream_end**：

```json
{
  "type": "voice_stream_end",
  "stream_id": "tts_20260816_001",
  "total_chunks": 42,
  "total_bytes": 123456,
  "send_timestamp": 1742524804567
}
```

**pong**：

```json
{ "type": "pong", "timestamp": 1742524800000 }
```

**voice_input_result**（成功 / 失败两态）：

```json
{ "type": "voice_input_result", "success": true, "text": "今天有点累" }
```

```json
{ "type": "voice_input_result", "success": false, "error": "没有检测到语音内容，请靠近麦克风说话", "error_type": "no_speech" }
```

`error_type` 枚举：`no_speech` / `service_error` / `exception`。

### 5.2 前端 → 服务端（上行）

| 消息类型 | 方向 | 说明 |
|----------|------|------|
| `ping` | 前端 | 心跳，每 25s 一次；35s 未收到 `pong` 判定假死重连 |
| `voice_input` | 前端 | 按压说话：松开后发送整段 base64 WAV（16kHz/单声道/16bit），服务端 ASR 后回 `voice_input_result` |
| `voice_capture` | 前端 | 长连接音频 chunk（base64），注入感知服务 openSMILE 做实时情感分析 |
| `chat` | 前端 | 遗留调试路径（绕过 Java 干预逻辑），主流对话应走 SSE |
| `instruction` | 前端 | 控制指令，如 `{"action": "toggle_camera"}` |
| `request_summary` | 前端 | 请求生成日报 |

```json
// voice_input 示例
{ "type": "voice_input", "data": "<base64 WAV>", "sampleRate": 16000, "channels": 1, "timestamp": 1742524800000 }

// ping 示例
{ "type": "ping", "timestamp": 1742524800000 }
```

### 5.3 Agent → 感知服务（后端上行，前端不发送）

Agent（`Agent/src/utils/websocket_client.py`、`tts.py`）作为 WS 客户端连接 `/ws`：

| 消息类型 | 说明 |
|----------|------|
| `agent_heartbeat` | 声明本连接为 Agent 客户端 |
| `tts_stream_start` | 声明本连接为 TTS 专用通道（音频块绕过广播队列直发前端） |
| `voice_stream` / `voice_stream_end` | 流式音频块与结束标记（同 5.1 格式，`send_timestamp` 由感知服务附加） |
| `voice_play` | 非流式整段音频广播（遗留） |

**重连约定**：前端 `onclose`/`onerror` 后 3s 自动重连（`setTimeout(connectPerceptionBus, 3000)`）。

---

## 六、SSE 帧协议逐帧定义

适用两段链路：Agent → Java（3.1）与 Java → 前端（2.3）。数据行格式 `data: <json>\n\n`。

### 6.1 非末帧（逐字流式）

```json
data: {"chunk": "我", "is_end": false}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `chunk` | string | 单字符/token |
| `is_end` | boolean | 恒为 `false` |

### 6.2 末帧（Agent 原始输出，Java 收到后重组）

```json
data: {"chunk": "。", "is_end": true, "reply": "完整关怀回复文本", "vector": {"喜悦": 0.2, "悲伤": 0.8, "愤怒": 0.1, "恐惧": 0.0, "厌恶": 0.0, "惊讶": 0.3, "踏实感": 0.1, "期待": 0.2}, "ui_action": {"color": "blue", "pulse": "medium"}, "action": "subtle", "urgency": "medium", "strategy": "共情倾听", "intervention_score": 0.65, "trace_id": "a1b2c3d4e5f60718", "timestamp_ms": 1749991234567, "session_id": "sess_abc123"}
```

| 字段 | 类型 | 出现时机 | 说明 |
|------|------|----------|------|
| `chunk` | string | 每帧 | 末帧为回复最后一个字符（空回复时为 `""`） |
| `is_end` | boolean | 每帧 | `true` 标记末帧 |
| `reply` | string | 末帧 | 完整回复全文 |
| `vector` | object | 末帧 | OCC 八维向量（键：喜悦/悲伤/愤怒/恐惧/厌恶/惊讶/踏实感/期待；值 0.0~1.0；空回复时为 `{}`） |
| `ui_action` | object | 末帧 | `{color, pulse}`，见 6.4 |
| `action` | string | 末帧 | `silent` / `subtle` / `intervene`，见 6.5 |
| `urgency` | string | 末帧 | `low` / `medium` / `high` |
| `strategy` | string | 末帧（可缺席） | 心理学策略名（如"5-4-3-2-1着陆技术"），仅非 None 时输出 |
| `intervention_score` | float | 末帧 | 0.0~1.0，Agent 决策评分 |
| `trace_id` | string | 末帧 | 调用追踪 ID（Agent 生成 `uuid4().hex[:16]`；Java 重写为自身值后透传） |
| `timestamp_ms` | long | 末帧 | 毫秒时间戳（Java→前端帧为 Java 侧时间） |
| `session_id` | string | 末帧 | 会话 ID |

### 6.3 末帧（Java → 前端最终帧，含 intervention_alert）

> **`intervention_alert` 由 Java `ChatController` 注入，Agent 不产出此字段**（旧 backend 契约完全缺失，本次修正）。单帧模式：末帧只发送一次，弹窗信息合并其中。

```json
data: {"chunk": "。", "is_end": true, "reply": "...", "vector": {...}, "ui_action": {...}, "action": "subtle", "urgency": "medium", "strategy": "共情倾听", "intervention_score": 0.65, "trace_id": "a1b2c3d4e5f60718", "timestamp_ms": 1749991234567, "session_id": "sess_abc123", "intervention_alert": {"show_popup": true, "urgency": "medium", "message": "婉晴感受到你可能心情有些不好，需要聊聊吗？"}}
```

`intervention_alert` 字段（`AgentInvokeResp.InterventionAlert`，统一 snake_case）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `show_popup` | boolean | 是否弹干预弹窗。Java 规则：`action != "silent" && urgency != "low"`；`silent` 时强制 `false` 且 `urgency` 强制 `low` |
| `urgency` | string | 弹窗紧迫度（与帧顶层 `urgency` 同源） |
| `message` | string | 弹窗文案：`reply` 截断 30 字符加省略号；`reply` 为空时按 urgency 兜底（high→"婉晴很担心你，现在方便聊一聊吗？" / medium→"婉晴感受到你可能心情有些不好，需要聊聊吗？" / low→"婉晴在这里，随时愿意倾听。"） |

**SSE 事件名约定（Java SseEmitter）**：

| 事件名 | 说明 |
|--------|------|
| `message` | 数据帧（非末帧 + 末帧均用此名） |
| `end` | 流结束标记（仅 comment "婉晴回复完毕"，无 data） |
| `error` | 错误帧（见 6.6） |

前端解析时兼容 `data:` 与 `data: `（有无空格）两种前缀。

### 6.4 ui_action 枚举

| color | 语义（Python 输出） | 前端光晕映射（COLOR_MAP） | pulse | 前端强度（PULSE_MAP） |
|-------|--------------------|--------------------------|-------|----------------------|
| `blue` | 焦虑/悲伤 | negative_sad | `slow` | 0.2 |
| `orange` | 沮丧/低落 | positive_joy（已修复，暖色=积极） | `medium` | 0.5 |
| `green` | 喜悦/安心 | positive_joy | `fast` | 0.8 |
| `purple` | 愤怒/激动 | negative_anger | `very_fast` | 0.95 |
| `neutral` | 中性/平静 | neutral（光晕隐藏） | `slow` | 0.2 |

### 6.5 action 干预决策语义（三端统一）

| action | 语义 | 前端表现 | urgency 约束 |
|--------|------|----------|--------------|
| `silent` | 无显式回复干预（可有状态更新） | 不弹窗，静默模式 | 强制 `low`，`show_popup=false` |
| `subtle` | 轻干预/提示型响应 | 可弹低优先级提示 | 通常 low/medium |
| `intervene` | 显式深度干预回复 | 弹中/高优先级干预弹窗 | 通常 medium/high |

### 6.6 错误帧（Plan1-E）

Agent 流异常或调用前异常时，Java 以事件名 `error` 发送：

```json
data: {"is_end": true, "is_error": true, "error_code": "AGENT_SSE_ERROR", "error_message": "婉晴暂时无法回复，请稍后重试。", "recoverable": true, "reply": "婉晴暂时无法回复，请稍后重试。", "action": "subtle", "urgency": "low", "trace_id": "error-sse-1749991234567", "timestamp_ms": 1749991234567, "session_id": "sess_abc123"}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `is_error` | boolean | `true` 标记错误帧 |
| `error_code` | string | `AGENT_SSE_ERROR`（Agent SSE 流中断）/ `AGENT_PRE_CALL_ERROR`（调用前异常），后者 `trace_id` 前缀为 `error-precall-` |
| `error_message` | string | 人类可读错误描述 |
| `recoverable` | boolean | `true`=可重试，`false`=需人工介入 |

前端应优先检查 `is_error`，再按 `recoverable` 决定重试或降级提示。

### 6.7 OCC 八维情感向量

| 中文标签 | 英文 | 含义 | 高值提示 |
|----------|------|------|----------|
| 喜悦 | joy | 愉悦、正向反馈 | 微笑、眼神明亮 |
| 悲伤 | sadness | 失落、无助 | 眉头紧锁、声音低沉 |
| 愤怒 | anger | 挫败、被冒犯 | 脸红、语速加快 |
| 恐惧 | fear | 担忧、不安全感 | 眨眼增加、回避眼神 |
| 厌恶 | disgust | 排斥、反感 | 皱眉、鼻子皱起 |
| 惊讶 | surprise | 意外、震惊 | 眉毛抬高、嘴巴张开 |
| 踏实感 | well_grounding | 平静、安全、被支持 | 眼神稳定、放松 |
| 期待 | anticipation | 对未来的预期 | 眼神明亮、主动行为 |

- 前端雷达图标签顺序固定：`["喜悦","悲伤","愤怒","恐惧","厌恶","惊讶","踏实感","期待"]`，值域 0.0~1.0（`appStore` 归一化）。
- 向量最大值项即 `primary_emotion`（中文标签），前端经 `emotionMap` 映射立绘：喜悦→开心、踏实感/期待→平静、好奇/害羞/焦虑/无奈为扩展标签。
- **Agent 输出的 `primary_emotion` 必须取自 OCC 中文标签列表。**

---

## 七、Redis key 约定（跨服务集成总线）

Redis（6379）是三服务集成的数据总线。全量 key 清单（含两份旧契约均未记载的 5 个）：

| Key | 类型 | 写入方 | 读取方 | TTL/长度 | 内容 |
|-----|------|--------|--------|----------|------|
| `emotion:realtime:{session_id}` | String(JSON) | 感知引擎 `_write_to_redis()` 10Hz 覆盖 SET | Agent `collect_perception` 节点（每轮推理一次，非 10Hz） | 无 TTL | 多模态感知快照，schema 见下 |
| `camera:frame:{session_id}` | String(base64) | 感知引擎（同上，JPEG quality=70） | Agent（Qwen-VL 视觉分析） | 30s | 最新摄像头帧 |
| `session:{session_id}:history` | List(JSON) | Java ChatController（LPUSH+trim 0..19+expire 2h）；Python `short_term` 亦读写 | Java（拼 `conversation_history`）；Agent（Java 未传时兜底读取） | 2 小时 / 保留 20 条 | `{role: "user"\|"ai", content, timestamp}`，LPUSH 新在前 |
| `session:{session_id}:summary` | String | Python `summarize_history`（满 20 条触发摘要压缩，保留最近 5 条） | Python（拼 prompt 上下文） | SESSION_TTL 7200s | 历史摘要 |
| `session:{session_id}:last_active` | String | Python | Python（会话过期判定） | SESSION_TTL 7200s | 最后活跃时间 |
| `session:turn_index:{session_id}` | String(计数器) | Java ConversationController（INCR） | Java | 无 TTL | 会话轮次号（原子自增，落 `session_logs.turn_index`） |
| `emotion:history:{session_id}` | List(JSON) | Java ChatController（每轮末帧后 LPUSH） | Java（下轮调 Agent 前取 10 条） | 2 小时 / 保留 20 条 | `{timestamp, primary_emotion, intensity}`，最新在前 |
| `feedback:stats:{session_id}` | String(JSON) | Java FeedbackServiceImpl | Java（计算 `user_rejection_penalty`） | 24 小时 | `{accepted: N, rejected: N, ignored: N, rejection_rate: 0.0~1.0}` |

### emotion:realtime:{session_id} Value Schema

```json
{
  "timestamp": 1709123456789,
  "session_id": "sess_abc123",
  "au": {
    "AU1": 0.12, "AU2": 0.08, "AU4": 0.85, "AU5": 0.15, "AU6": 0.12, "AU7": 0.05,
    "AU9": 0.03, "AU12": 0.08, "AU15": 0.72, "AU17": 0.20, "AU25": 0.10, "AU26": 0.05,
    "primary_emotion": "sad",
    "confidence": 0.78
  },
  "head_pose": { "pitch": -12.5, "yaw": 3.2, "roll": 1.1 },
  "blink_rate": 28.5,
  "audio": {
    "pitch": 210.5, "loudness": 0.65,
    "mfcc": [-2.34, 1.21, 0.88, -0.45, 0.12, 0.33, -0.21, 0.55, 0.18, -0.09, 0.22, -0.33, 0.11],
    "speaking": false
  },
  "focus_level": 0.42
}
```

| 字段 | 类型 | 来源 | 说明 |
|------|------|------|------|
| `timestamp` | long | 感知引擎 | Unix 毫秒时间戳 |
| `au.*` | float 0~1 | HuggingFace FER + 情绪→AU 反推 | 面部动作单元强度（AU4=皱眉，AU12=微笑等） |
| `au.primary_emotion` | string | 模型输出 | 英文标签：angry/disgust/fear/happy/neutral/sad/surprise |
| `au.confidence` | float | 模型输出 | 置信度 0~1 |
| `head_pose.pitch` | float | MediaPipe | 俯仰角（度），负=低头（-40° 以下视为走神/看手机） |
| `head_pose.yaw` / `roll` | float | MediaPipe | 偏航/翻滚角（度） |
| `blink_rate` | float | MediaPipe | 眨眼频率（次/分钟），>25 提示焦虑 |
| `audio.pitch` | float | openSMILE eGeMAPS | 基频 F0（Hz），>250 高唤醒 |
| `audio.loudness` | float | openSMILE | 响度（0~1 归一化） |
| `audio.mfcc` | list[13] | openSMILE | 13 维 MFCC |
| `audio.speaking` | bool | VAD | 是否正在说话（`voicing_prob` 已计算但未入 Redis） |
| `focus_level` | float 0~1 | 感知引擎融合 | 专注度（头部稳定性+眨眼评分） |

**降级策略**：key 不存在（Redis miss）时，Agent `get_latest_perception` 返回 None → 使用默认中性感知数据，专注模式降级为走神模式。

---

## 八、已知实现状态说明

| ID | 状态 | 说明 |
|----|------|------|
| S-01 | 已实现 | 前端 `App.vue` 挂载时调用 `POST /api/v1/session/start`（20 次重试 × 3s），使用真实 `session_id`（旧 TODO T-02 已修复） |
| S-02 | 已实现 | SSE 末帧 `intervention_alert` 注入 + 前端弹窗 + `POST /api/v1/feedback` 反馈闭环 |
| S-03 | 已实现 | Agent → Java `/internal/conversation/log` 回调落库（含 Redis INCR 轮次） |
| S-04 | 已实现 | TTS 流式通道（`tts_stream_start` + `voice_stream`/`voice_stream_end`），支持 Edge TTS 与 DashScope 双 provider |
| S-05 | 已实现 | `voice_play` 仅接受 `data:audio` base64 内嵌（旧 TODO T-04 安全风险已消除） |
| S-06 | 已实现 | WS 心跳（ping 25s / pong 超时 35s / 假死重连）；组件卸载清理 SSE AbortController、WS 重连定时器、心跳定时器（旧 TODO T-06/T-07 已修复） |
| S-07 | 遗留 | `/internal/v1/session/update` 仅存在于感知服务（8000），Agent（8001）未实现同路径端点；当前 Java 始终调感知服务实例，行为正确，但需保持调用目标不漂移 |
| S-08 | 遗留 | 感知服务存在遗留 `/internal/v1/agent/invoke`（本地规则引擎降级），其 SSE 输出缺 `trace_id`/`timestamp_ms`/`session_id`/`intervention_score`，若误接入会产生契约不一致 |
| S-09 | 遗留 | `history_limit` 字段 Java 发送但 Python Agent 不消费（无害冗余字段） |
| S-10 | 遗留 | Agent `/internal/v1/rag/upload` 仅接受 `.md`/`.txt`，前端/文档若宣传 PDF 支持会得到 400 |
| S-11 | 遗留 | `/internal/conversation/log` 与感知 `/internal/v1/session/update` 无鉴权（依赖内网隔离），生产环境需网络隔离或 mTLS |
| S-12 | 观察项 | `ChatController` 将 `session.status`（`"ready"`）作为 `task_phase` 传给 Agent，语义与字段名不符，消费方注意 |

---

## 九、契约修复记录

本次合并以代码为准，修正的漂移点如下：

| # | 类别 | 修复内容 |
|---|------|----------|
| 1 | 结构 | **双文档合一**：`backend/API_Contract.md`（240 行，较旧）与 `frontend/API_Contract.md`（435 行，较新）合并为本文档 `docs/API_CONTRACT.md`，两份旧文件待删除 |
| 2 | 缺失 | **SSE 末帧补 `intervention_alert`**：旧 backend 契约完全缺失该字段；本次依据 `ChatController` 约 196-263 行补全 `show_popup`/`urgency`/`message` 三字段、Java 注入规则（silent 强制 low + 不弹窗、reply 截断 30 字符、按 urgency 兜底文案）及"Agent 不产出此字段、由 Java 注入"的职责边界 |
| 3 | 缺失 | **补 `POST /api/v1/feedback`**：两份旧契约均未记载该前端接口；补全请求体（`session_id`/`choice`/`emotion_vector`/`current_emotion`）、choice 枚举校验与 Redis 副作用（`feedback:stats` → `user_rejection_penalty` 闭环） |
| 4 | 缺失 | **补 `POST /internal/conversation/log`**：两份旧契约均未记载；补全 Agent 回调 Java 的会话日志落库链路（`callback.py` → `ConversationController` → MySQL `session_logs`）、10 字段请求体、`X-Internal-Source` 头与 Redis INCR 轮次副作用 |
| 5 | 缺失 | **补 TTS 流式 WS 协议**：`voice_stream`/`voice_stream_end`/`tts_stream_start`/`agent_heartbeat` 四个消息类型两份旧契约均未记载；含 `stream_id`/`chunk_index`/`send_timestamp` 字段定义 |
| 6 | 缺失 | **补 WS 上行消息**：`voice_input`（按压说话 ASR）与 `voice_input_result`（含 `error_type` 枚举）、`ping`/`pong` 心跳、`voice_capture`、`instruction`、`request_summary`、遗留 `chat` |
| 7 | 缺失 | **补 Redis key 5 个**：`session:turn_index:*`、`feedback:stats:*`、`emotion:history:*`、`camera:frame:*`、`session:*:summary`/`last_active`（旧契约仅记载 `emotion:realtime:*` 与 `session:*:history`） |
| 8 | 漂移 | **`/api/v1/session/start` 请求字段名**：旧契约写 camelCase（`subjectName`/`experimentGroup`）且 experimentGroup 选填；代码实际为 snake_case（`subject_name`/`experiment_group`，`@JsonProperty` 映射）且**两字段均必填**（`@NotBlank`），前端实际传 `anonymous`/`default` |
| 9 | 漂移 | **`voice_play` 数据格式**：旧契约称"仅限 `http://localhost:8000` 开头的音频 URL"；代码实际为 `data:audio/mp3;base64,...` 内嵌数据，前端仅接受 `data:audio` 前缀并拒绝一切外部 URL |
| 10 | 漂移 | **知识库上传文件类型**：旧 backend 契约写"Markdown 或 PDF"；Agent 代码仅接受 `.md`/`.txt`（PDF 返回 400） |
| 11 | 漂移 | **`/internal/v1/agent/invoke` 请求体**：补全 `conversation_history`（JSON 字符串列表）、`user_rejection_penalty`、`user_id`、`task_phase` 字段；标注 `history_limit` 被 Python 忽略；纠正 `task_phase` 实际传值为 `session.status`（`"ready"`）而非旧契约的 `"companion_task"` |
| 12 | 漂移 | **`perception_update.data` 补 `timestamp_ms`**：整数毫秒字段（与 SSE 时间戳对齐），旧契约只记载 ISO 字符串 `timestamp` |
| 13 | 漂移 | **错误帧补 `AGENT_PRE_CALL_ERROR`**：旧契约仅示例 `AGENT_SSE_ERROR`；补全两种错误码与 `error-precall-` trace 前缀，及 SSE 事件名 `message`/`end`/`error` 约定 |
| 14 | 漂移 | **`/internal/v1/session/update` 响应格式**：明确为 `{code: 0, ...}` 私有格式，非 Java `Result` 200 格式，避免调用方误判 |
| 15 | 补全 | **补健康/信息端点**：Java `GET /health`、`GET /api/v1/info`（裸 JSON 非 Result 包装）、Agent `GET /health`、感知 `GET /`、`/health`、`/model_status`（两份旧契约均未记载） |
| 16 | 补全 | **补感知服务遗留 `/internal/v1/agent/invoke`**：同路径双实现的风险说明（本地规则引擎降级、末帧缺 4 个 Plan1-A 字段） |

> 环境变量仅引用 `.env.example` 中的占位符（如 `VITE_API_BASE`、`JAVA_CALLBACK_URL`、`AGENT_BASE_URL`），文档不包含任何真实密钥或密码。
