package com.wanqing.ai.service.impl;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.wanqing.ai.entity.UserFeedback;
import com.wanqing.ai.mapper.UserFeedbackMapper;
import com.wanqing.ai.service.FeedbackService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;

/**
 * 用户干预反馈服务实现类
 *
 * 核心职责：
 *   1. 写入 MySQL（user_feedback 表），持久化存储每次干预弹窗的用户选择
 *   2. 同步写入 Redis（feedback:stats:{session_id}），供 Python Agent 实时读取反馈统计
 *
 * 依赖关系：
 *   - 被 FeedbackController 调用
 *   - 依赖 UserFeedbackMapper（MyBatis-Plus → MySQL）
 *   - 依赖 StringRedisTemplate（Redis）
 *   - 被 ChatController 依赖（读取反馈统计计算 user_rejection_penalty）
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class FeedbackServiceImpl implements FeedbackService {

    private final UserFeedbackMapper userFeedbackMapper;
    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;

    /** 反馈统计 Redis Key 前缀 */
    private static final String FEEDBACK_STATS_KEY_PREFIX = "feedback:stats:";

    /** 反馈统计数据在 Redis 中的过期时间（会话结束后仍保留 24 小时供分析） */
    private static final long STATS_TTL_HOURS = 24;

    @Override
    public void recordFeedback(String sessionId, String choice,
                               Map<String, Double> emotionVector,
                               String currentEmotion) {
        if (sessionId == null || sessionId.isBlank()) {
            log.warn("[Feedback] sessionId 为空，跳过记录");
            return;
        }
        if (choice == null) {
            choice = "ignored";
        }

        // 1. 写入 MySQL
        try {
            UserFeedback entity = new UserFeedback()
                    .setSessionId(sessionId)
                    .setChoice(choice)
                    .setCurrentEmotion(currentEmotion != null ? currentEmotion : "")
                    .setEmotionSnapshot(toJsonString(emotionVector))
                    .setFeedbackTime(LocalDateTime.now());
            userFeedbackMapper.insert(entity);
            log.info("[Feedback] MySQL 记录成功: sessionId={}, choice={}", sessionId, choice);
        } catch (Exception e) {
            log.error("[Feedback] MySQL 写入失败: {}", e.getMessage());
        }

        // 2. 同步写入 Redis（供 Python Agent 实时读取）
        try {
            syncFeedbackStatsToRedis(sessionId, choice);
        } catch (Exception e) {
            log.warn("[Feedback] Redis 同步失败: {}", e.getMessage());
        }
    }

    /**
     * 同步反馈统计数据到 Redis
     * Key: feedback:stats:{session_id}
     * Value: JSON {"accepted": N, "rejected": N, "ignored": N, "rejection_rate": 0.0~1.0, ...}
     */
    private void syncFeedbackStatsToRedis(String sessionId, String newChoice) {
        String key = FEEDBACK_STATS_KEY_PREFIX + sessionId;

        // 读取现有统计
        Map<String, Object> stats = readStatsFromRedis(key);

        // 更新计数
        stats.put("last_choice", newChoice);
        stats.put("last_updated", System.currentTimeMillis());

        long accepted = stats.containsKey("accepted") ? ((Number) stats.get("accepted")).longValue() : 0;
        long rejected = stats.containsKey("rejected") ? ((Number) stats.get("rejected")).longValue() : 0;
        long ignored = stats.containsKey("ignored") ? ((Number) stats.get("ignored")).longValue() : 0;

        switch (newChoice) {
            case "accepted" -> accepted++;
            case "rejected" -> rejected++;
            default -> ignored++;
        }

        stats.put("accepted", accepted);
        stats.put("rejected", rejected);
        stats.put("ignored", ignored);

        // 计算拒绝率
        long total = accepted + rejected + ignored;
        if (total > 0) {
            stats.put("rejection_rate", (double) rejected / total);
        } else {
            stats.put("rejection_rate", 0.0);
        }

        String json = toJsonString(stats);
        redisTemplate.opsForValue().set(key, json, STATS_TTL_HOURS, TimeUnit.HOURS);
        log.debug("[Feedback] Redis 统计已更新: key={}, stats={}", key, json);
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> readStatsFromRedis(String key) {
        String json = redisTemplate.opsForValue().get(key);
        if (json == null || json.isBlank()) {
            return new HashMap<>();
        }
        try {
            return objectMapper.readValue(json, Map.class);
        } catch (JsonProcessingException e) {
            log.warn("[Feedback] Redis 统计 JSON 解析失败，返回空: {}", e.getMessage());
            return new HashMap<>();
        }
    }

    @Override
    public Map<String, Object> getFeedbackStats(String sessionId) {
        if (sessionId == null || sessionId.isBlank()) {
            return Map.of("accepted", 0L, "rejected", 0L, "ignored", 0L, "rejection_rate", 0.0);
        }
        String key = FEEDBACK_STATS_KEY_PREFIX + sessionId;
        return readStatsFromRedis(key);
    }

    private String toJsonString(Object obj) {
        try {
            return objectMapper.writeValueAsString(obj);
        } catch (JsonProcessingException e) {
            log.warn("[Feedback] JSON 序列化失败: {}", e.getMessage());
            return "{}";
        }
    }
}
