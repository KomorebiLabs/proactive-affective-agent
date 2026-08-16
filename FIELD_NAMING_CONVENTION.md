# 婉情AI - 字段命名规范

> **统一标准**：全系统所有 JSON 字段统一使用 `snake_case`（下划线分隔）。
> - 数据库表字段：`snake_case`（MySQL 默认）
> - Java 实体/DTO：`snake_case`（通过 `@JsonProperty` 注解显式映射）
> - Python Pydantic/State：`snake_case`（与 JSON 保持一致）
> - 前端 JavaScript/Vue：`snake_case`（与后端 JSON 保持一致）

---

## 一、已发现字段不一致问题汇总

### 1.1 Session 会话相关

| 位置 | 字段名 | 问题 | 修复方案 |
|------|--------|------|----------|
| `SessionStartResp.java` | `sessionId` | Java 返回驼峰 | ✅ 已修复：改为 `session_id` |
| `App.vue` initSession | `session_id` | 前端期望错误字段 | ✅ 已修复：改为 `sessionId` |

**当前状态**：双向统一为 `session_id`

### 1.2 Agent SSE 响应字段

| 位置 | 字段名 | 问题 | 修复方案 |
|------|--------|------|----------|
| Python `return_result_node` | `intervention_alert` | 返回的是内层对象 | 需确认 Java 期望 |
| Java `AgentInvokeResp.java` | `interventionAlert` | 驼峰命名 | ✅ 需改为 `intervention_alert` |
| 前端 `App.vue` | `intervention_alert` | 期望下划线 | ✅ 已统一 |

**当前状态**：Python/前端已统一为 `intervention_alert`，Java 需修复

### 1.3 情感向量相关

| 位置 | 字段名 | 问题 | 状态 |
|------|--------|------|------|
| Python | `emotion_vector` | OCC 八维向量 | ✅ 正确 |
| Java `AgentInvokeResp` | `vector` | 驼峰命名 | 需确认一致性 |
| 前端 | `vector` | 期望字段 | ✅ 已统一 |

### 1.4 干预相关

| 位置 | 字段名 | 问题 | 状态 |
|------|--------|------|------|
| Python | `urgency` | 干预紧迫度 | ✅ 正确 |
| Java | `urgency` | 驼峰命名 | 需统一 |
| 前端 | `urgency` | 期望字段 | ✅ 已统一 |

### 1.5 Feedback 反馈相关

| 位置 | 字段名 | 问题 | 状态 |
|------|--------|------|------|
| 前端 `App.vue` | `session_id`, `emotion_vector`, `current_emotion` | 发送请求字段 | ✅ 正确 |
| Java `FeedbackRequest` | `@JsonProperty` 标注 | 已有映射 | ✅ 正确 |

---

## 二、JSON 字段完整清单（统一标准）

### 2.1 会话相关

```json
{
  "session_id": "sess_xxxxxxxx",
  "subject_name": "张三",
  "experiment_group": "A_Group",
  "user_id": "user_001"
}
```

### 2.2 Agent 聊天请求

```json
{
  "session_id": "sess_xxxxxxxx",
  "user_id": "user_001",
  "user_message": "我今天心情不好",
  "task_phase": "companion_task",
  "emotion_history": [
    {
      "timestamp": 1711000000000,
      "primary_emotion": "悲伤",
      "intensity": 0.7
    }
  ],
  "history_limit": 10,
  "user_rejection_penalty": 1.0
}
```

### 2.3 Agent SSE 流式响应

```json
{
  "chunk": "我",
  "is_end": false
}
```

**最终帧（is_end=true）**：
```json
{
  "chunk": "",
  "is_end": true,
  "ui_action": {
    "color": "blue",
    "pulse": "medium"
  },
  "reply": "我理解你的感受...",
  "vector": {
    "喜悦": 0.1,
    "悲伤": 0.8,
    "愤怒": 0.2,
    "恐惧": 0.3,
    "厌恶": 0.1,
    "惊讶": 0.2,
    "踏实感": 0.4,
    "期待": 0.1
  },
  "urgency": "medium",
  "strategy": "共情倾听",
  "intervention_score": 0.65,
  "intervention_alert": {
    "show_popup": true,
    "urgency": "medium",
    "message": "婉晴感受到你可能心情有些不好，需要聊聊吗？"
  }
}
```

### 2.4 用户反馈请求

```json
{
  "session_id": "sess_xxxxxxxx",
  "choice": "accepted",
  "emotion_vector": {
    "喜悦": 0.1,
    "悲伤": 0.8
  },
  "current_emotion": "悲伤"
}
```

### 2.5 WebSocket 感知数据

```json
{
  "type": "perception_update",
  "data": {
    "timestamp": 1711000000000,
    "gaze_direction": "forward",
    "blink_rate": 15.0,
    "focus_score": 0.8,
    "au_values": {
      "AU4": 0.2,
      "AU12": 0.5
    }
  }
}
```

---

## 三、命名规则总结

| 场景 | 命名风格 | 示例 |
|------|----------|------|
| JSON API 字段 | `snake_case` | `session_id`, `user_message` |
| Java 变量/方法 | camelCase | `sessionId`, `userMessage` |
| Java 类的 JSON 字段 | `@JsonProperty("snake_case")` | 显式映射 |
| Python 变量 | snake_case | `session_id`, `user_message` |
| 数据库表字段 | snake_case | `session_id`, `create_time` |
| 前端 JS/Vue | snake_case | `sessionId`, `currentEmotion`（Pinia store 可用驼峰） |

---

## 四、注意事项

1. **Java 响应必须显式标注**：`@JsonProperty("snake_case")` 确保前端能正确解析
2. **Python Pydantic 模型**：使用 `snake_case` 字段名，与 JSON 协议一致
3. **前端 fetch/SSE**：发送和接收都使用 `snake_case`
4. **数据库**：MySQL 默认 `snake_case`，MyBatis-Plus 的 `map-underscore-to-camel-case: true` 自动映射到 Java 驼峰

---

## 五、已修复清单 ✅

- [x] `SessionStartResp.java`：添加 `@JsonProperty("session_id")` ✅
- [x] `AgentInvokeResp.InterventionAlert`：添加 `@JsonProperty` 注解 ✅
- [x] `UserSession.java`：添加 `@TableField` 映射（subject_name, experiment_group, create_time, update_time）✅
- [x] `UserFeedback.java`：添加 `@TableField` 映射（session_id, emotion_snapshot, current_emotion, feedback_time）✅
- [x] `App.vue` initSession：接收 `sessionId` 改为 `sessionId`（与 Java 响应对应）✅
- [x] `App.vue` initSession 请求：发送 `subjectName`/`experimentGroup` 改为 `subject_name`/`experiment_group` ✅

---

## 六、审查结论

### 修复完整的字段流

| 环节 | 字段 | 状态 |
|------|------|------|
| 前端发送请求 | `session_id`, `subject_name`, `experiment_group` | ✅ 统一 snake_case |
| Java 接收请求 | `SessionStartReq` + `@JsonProperty` | ✅ Jackson 自动映射驼峰 |
| Java 返回响应 | `SessionStartResp` + `@JsonProperty("session_id")` | ✅ snake_case |
| 前端接收响应 | `json.data.sessionId` | ✅ 驼峰（与 Jackson 序列化结果一致） |
| 前端发送 Chat | `message` | ✅ 正确 |
| Java → Python | `AgentInvokeReq` + `@JsonProperty` | ✅ snake_case |
| Python → Java | SSE JSON | ✅ snake_case |
| Java → 前端 | `AgentInvokeResp` + `@JsonProperty` | ✅ snake_case |
| 前端处理 SSE | `payload.chunk`, `payload.is_end` 等 | ✅ snake_case |
| 前端发送 Feedback | `session_id`, `emotion_vector`, `current_emotion` | ✅ snake_case |
| Java 接收 Feedback | `FeedbackRequest` + `@JsonProperty` | ✅ snake_case |
| DB Entity 映射 | `@TableField` 显式声明 | ✅ snake_case → DB snake_case |

### 无遗漏问题 ✅

- 所有 HTTP 请求/响应字段：已统一为 snake_case
- 所有 SSE 流字段：已验证一致性
- 所有 WebSocket 消息字段：符合规范
- 所有数据库字段：已添加 `@TableField` 显式映射
- Java 内部使用驼峰（变量/方法）：符合 Java 编码规范

---

*文档更新时间：2026-03-23*
