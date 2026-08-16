package com.wanqing.ai.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;

/**
 * Redis 情感历史服务
 * <p>
 * 职责：
 * 1. 写入每轮情感分析结果（Python Agent 通过 /internal/v1/agent/invoke 返回后，Java 写入 Redis）
 * 2. 读取情感历史供下次 Agent 调用时传入 Python
 * 3. 情感历史 Key 格式: emotion:history:{session_id}
 * 4. 最多保留最近 20 条记录（超出则丢弃最早的）
 * <p>
 * 注意：Redis 中的原始感知数据（emotion:realtime:{session_id}）由 Python 感知微服务直接写入，
 * Java 不负责写入，只负责管理情感历史记录。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class EmotionHistoryService {

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;

    /** 情感历史 Redis Key 前缀 */
    private static final String EMOTION_HISTORY_KEY_PREFIX = "emotion:history:";

    /** 最多保留的历史条数 */
    private static final int MAX_HISTORY_SIZE = 20;

    /**
     * 追加一条情感历史记录（插入到列表头部，最新在前）
     *
     * @param sessionId       会话ID
     * @param emotionEntry    情感条目，含 primary_emotion / intensity / timestamp
     */
    public void appendEmotionHistory(String sessionId, Map<String, Object> emotionEntry) {
        if (sessionId == null || sessionId.isBlank() || emotionEntry == null) {
            return;
        }
        try {
            String key = EMOTION_HISTORY_KEY_PREFIX + sessionId;
            String json = objectMapper.writeValueAsString(emotionEntry);

            redisTemplate.opsForList().leftPush(key, json);

            Long size = redisTemplate.opsForList().size(key);
            if (size != null && size > MAX_HISTORY_SIZE) {
                redisTemplate.opsForList().trim(key, 0, MAX_HISTORY_SIZE - 1);
            }

            redisTemplate.expire(key, java.time.Duration.ofHours(2));

            log.debug("[EmotionHistory] 追加记录: session={}, emotion={}, intensity={}",
                    sessionId,
                    emotionEntry.get("primary_emotion"),
                    emotionEntry.get("intensity"));
        } catch (JsonProcessingException e) {
            log.warn("[EmotionHistory] JSON 序列化失败: {}", e.getMessage());
        } catch (Exception e) {
            log.warn("[EmotionHistory] 写入情感历史失败: {}", e.getMessage());
        }
    }

    /**
     * 读取当前会话的情感历史
     *
     * @param sessionId 会话ID
     * @param limit      最多返回条数（默认 10）
     * @return 按时间升序排列的情感历史列表
     */
    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> getEmotionHistory(String sessionId, int limit) {
        if (sessionId == null || sessionId.isBlank()) {
            return Collections.emptyList();
        }
        try {
            String key = EMOTION_HISTORY_KEY_PREFIX + sessionId;
            List<String> rawList = redisTemplate.opsForList().range(key, 0, limit - 1);
            if (rawList == null || rawList.isEmpty()) {
                return Collections.emptyList();
            }

            List<Map<String, Object>> result = new ArrayList<>();
            // LPUSH 的顺序：0是最新，但我们需要传给 Python 按时间升序
            // 所以反转列表
            List<String> reversed = new ArrayList<>(rawList);
            Collections.reverse(reversed);

            for (String json : reversed) {
                try {
                    Map<String, Object> entry = objectMapper.readValue(json, Map.class);
                    if (entry != null) {
                        result.add(entry);
                    }
                } catch (JsonProcessingException e) {
                    log.warn("[EmotionHistory] 解析情感历史条目失败: {}", e.getMessage());
                }
            }
            return result;
        } catch (Exception e) {
            log.warn("[EmotionHistory] 读取情感历史失败: {}", e.getMessage());
            return Collections.emptyList();
        }
    }

    /**
     * 简化版：读取最近 N 条（供 Agent 调用时使用）
     */
    public List<Map<String, Object>> getEmotionHistory(String sessionId) {
        return getEmotionHistory(sessionId, MAX_HISTORY_SIZE);
    }
}
