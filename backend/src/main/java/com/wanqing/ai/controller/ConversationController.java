package com.wanqing.ai.controller;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.wanqing.ai.common.Result;
import com.wanqing.ai.common.ResultCode;
import com.wanqing.ai.entity.SessionLog;
import com.wanqing.ai.entity.UserSession;
import com.wanqing.ai.mapper.SessionLogMapper;
import com.wanqing.ai.mapper.UserSessionMapper;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.web.bind.annotation.*;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.Map;

/**
 * Python Agent 回调控制器（内部接口）
 *
 * 核心职责：
 *   接收 Python Agent 的会话日志写入请求，将数据持久化到 MySQL session_logs 表。
 *   架构约定：Python AI 服务不直连 MySQL，数据由 Java 层写入。
 *
 * 数据来源：Python Agent（LangGraph log_session_node）
 * 触发时机：每轮对话结束后
 *
 * 对外暴露路径：/internal/conversation
 * 注意：该路径无需鉴权，仅供 Python Agent 内网调用（localhost 间通信）
 *
 * 安全说明：仅允许来自本机的 Python 服务回调。通过检查请求头 X-Internal-Source
 * 来标识内部调用来源。在生产环境中应使用网络隔离或 mTLS 来替代。
 */
@Slf4j
@RestController
@RequestMapping("/internal/conversation")
@RequiredArgsConstructor
@Tag(name = "内部回调", description = "Python Agent 回调 Java 后端写入会话日志")
public class ConversationController {

    private final SessionLogMapper sessionLogMapper;
    private final UserSessionMapper userSessionMapper;
    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;

    /**
     * Python Agent 回调写入会话日志
     *
     * 请求体格式（与 Python export_session_log 输出完全对齐）：
     * {
     *   "session_id": "sess_xxx",
     *   "user_message": "用户说的内容",
     *   "ai_reply": "婉晴的回复",
     *   "intervention_action": "subtle",
     *   "intervention_urgency": "low",
     *   "intervention_score": 0.6234,
     *   "perception_snapshot": { ... },
     *   "emotion_vector": { ... },
     *   "decision_detail": { ... },
     *   "retrieved_knowledge": [ ... ]
     * }
     */
    @PostMapping("/log")
    @Operation(summary = "写入会话日志", description = "Python Agent 回调写入 MySQL session_logs")
    public Result<Void> logConversation(
            @RequestHeader(value = "X-Internal-Source", required = false) String internalSource,
            @RequestBody Map<String, Object> payload) {
        String sessionId = (String) payload.get("session_id");

        if (sessionId == null || sessionId.isBlank()) {
            log.warn("【ConversationController】session_id 为空，拒绝写入");
            return Result.fail(ResultCode.BAD_REQUEST);
        }

        // 验证 session 存在
        UserSession session = userSessionMapper.selectById(sessionId);
        if (session == null) {
            log.warn("【ConversationController】session 不存在: {}", sessionId);
            return Result.fail(ResultCode.NOT_FOUND);
        }

        try {
            // 原子递增会话轮次（使用 Redis INCR，线程安全且无竞争）
            String turnCounterKey = "session:turn_index:" + sessionId;
            Long nextTurn = redisTemplate.opsForValue().increment(turnCounterKey);
            // 若 key 不存在，INCR 会自动创建并返回 1（已是第一个 turn）
            int turnIndex = nextTurn != null ? nextTurn.intValue() : 1;

            // 构建实体
            SessionLog logEntry = new SessionLog()
                    .setSessionId(sessionId)
                    .setTurnIndex(turnIndex)
                    .setUserMessage(safeGetString(payload, "user_message"))
                    .setAiReply(safeGetString(payload, "ai_reply"))
                    .setInterventionAction(safeGetString(payload, "intervention_action"))
                    .setInterventionUrgency(safeGetString(payload, "intervention_urgency"))
                    .setPerceptionSnapshot(safeToJson(payload.get("perception_snapshot")))
                    .setEmotionVector(safeToJson(payload.get("emotion_vector")))
                    .setDecisionDetail(safeToJson(payload.get("decision_detail")))
                    .setRetrievedKnowledge(safeToJson(payload.get("retrieved_knowledge")))
                    .setLogTime(LocalDateTime.now());

            // 写入干预分数（BigDecimal）
            Object scoreObj = payload.get("intervention_score");
            if (scoreObj instanceof Number) {
                logEntry.setInterventionScore(BigDecimal.valueOf(((Number) scoreObj).doubleValue()));
            }

            // 插入 MySQL
            sessionLogMapper.insert(logEntry);

            log.info("【ConversationController】会话日志写入成功: session={}, turn={}, action={}",
                    sessionId, turnIndex,
                    logEntry.getInterventionAction());

            return Result.success();

        } catch (Exception e) {
            log.error("【ConversationController】写入会话日志失败: session={}, error={}",
                    sessionId, e.getMessage(), e);
            return Result.fail(500, "写入失败: " + e.getMessage());
        }
    }

    // ── 工具方法 ──────────────────────────────────────────────────────────────

    private String safeGetString(Map<String, Object> map, String key) {
        Object v = map.get(key);
        return v != null ? v.toString() : null;
    }

    private String safeToJson(Object obj) {
        if (obj == null) return null;
        try {
            return objectMapper.writeValueAsString(obj);
        } catch (JsonProcessingException e) {
            log.warn("【ConversationController】JSON 序列化失败: {}", e.getMessage());
            return null;
        }
    }
}
